"""
Tests for /rolewinrate command.
"""

import sqlite3

import pytest

from repositories.match_repository import MatchRepository
from repositories.player_repository import PlayerRepository


@pytest.fixture
def setup_role_data(repo_db_path):
    """Set up test data with enriched matches and lane roles."""
    player_repo = PlayerRepository(repo_db_path)
    match_repo = MatchRepository(repo_db_path)

    # Register test players
    player_repo.add(discord_id=100, discord_username="MidPlayer", initial_mmr=3000)
    player_repo.add(discord_id=200, discord_username="SafeLaner", initial_mmr=3000)
    player_repo.add(discord_id=300, discord_username="Offlaner", initial_mmr=3000)

    # Create some enriched matches with lane role data
    match_id_1 = match_repo.record_match(
        team1_ids=[100, 200, 300, 400, 500],
        team2_ids=[101, 201, 301, 401, 501],
        winning_team=1,
    )

    match_id_2 = match_repo.record_match(
        team1_ids=[100, 200, 300, 400, 500],
        team2_ids=[101, 201, 301, 401, 501],
        winning_team=2,
    )

    match_id_3 = match_repo.record_match(
        team1_ids=[100, 200, 300, 400, 500],
        team2_ids=[101, 201, 301, 401, 501],
        winning_team=1,
    )

    # Manually insert match_participants with lane_role data
    # (Simulating enriched matches)
    conn = sqlite3.connect(repo_db_path)
    cursor = conn.cursor()

    # Match 1: Player 100 mid (lane_role=2), team 1 wins
    cursor.execute(
        """
        UPDATE match_participants
        SET lane_role = 2
        WHERE match_id = ? AND discord_id = ?
        """,
        (match_id_1, 100),
    )

    # Match 2: Player 100 mid (lane_role=2), team 2 wins (player loses)
    cursor.execute(
        """
        UPDATE match_participants
        SET lane_role = 2
        WHERE match_id = ? AND discord_id = ?
        """,
        (match_id_2, 100),
    )

    # Match 3: Player 100 safe lane (lane_role=1), team 1 wins
    cursor.execute(
        """
        UPDATE match_participants
        SET lane_role = 1
        WHERE match_id = ? AND discord_id = ?
        """,
        (match_id_3, 100),
    )

    # Player 200 safe lane wins for all matches
    for mid in [match_id_1, match_id_2, match_id_3]:
        cursor.execute(
            """
            UPDATE match_participants
            SET lane_role = 1
            WHERE match_id = ? AND discord_id = ?
            """,
            (mid, 200),
        )

    # Player 300 offlane (lane_role=3)
    for mid in [match_id_1, match_id_2, match_id_3]:
        cursor.execute(
            """
            UPDATE match_participants
            SET lane_role = 3
            WHERE match_id = ? AND discord_id = ?
            """,
            (mid, 300),
        )

    conn.commit()
    conn.close()

    return {
        "player_repo": player_repo,
        "match_repo": match_repo,
        "db_path": repo_db_path,
    }


def test_rolewinrate_calculation(setup_role_data):
    """Test that lane role win rates are calculated correctly."""
    db_path = setup_role_data["db_path"]
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Query for player 100 (MidPlayer)
    cursor.execute(
        """
        SELECT
            lane_role,
            COUNT(*) as games,
            SUM(CASE WHEN won = 1 THEN 1 ELSE 0 END) as wins
        FROM match_participants
        WHERE discord_id = ? AND lane_role IS NOT NULL
        GROUP BY lane_role
        ORDER BY games DESC
        """,
        (100,),
    )

    results = cursor.fetchall()
    conn.close()

    # Player 100 played:
    # - 2 games mid (lane_role=2): 1 win, 1 loss
    # - 1 game safe (lane_role=1): 1 win
    assert len(results) == 2

    # Check mid lane stats (should be first with 2 games)
    mid_stats = next((r for r in results if r[0] == 2), None)
    assert mid_stats is not None
    assert mid_stats[1] == 2  # 2 games
    assert mid_stats[2] == 1  # 1 win

    # Check safe lane stats
    safe_stats = next((r for r in results if r[0] == 1), None)
    assert safe_stats is not None
    assert safe_stats[1] == 1  # 1 game
    assert safe_stats[2] == 1  # 1 win


def test_rolewinrate_no_enriched_data(repo_db_path):
    """Test behavior when player has no enriched matches."""
    player_repo = PlayerRepository(repo_db_path)
    player_repo.add(discord_id=999, discord_username="NewPlayer", initial_mmr=2000)

    conn = sqlite3.connect(repo_db_path)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            lane_role,
            COUNT(*) as games,
            SUM(CASE WHEN won = 1 THEN 1 ELSE 0 END) as wins
        FROM match_participants
        WHERE discord_id = ? AND lane_role IS NOT NULL
        GROUP BY lane_role
        """,
        (999,),
    )

    results = cursor.fetchall()
    conn.close()

    # Should have no results
    assert len(results) == 0


def test_rolewinrate_all_lanes(setup_role_data):
    """Test a player who has played all lane roles."""
    db_path = setup_role_data["db_path"]
    player_repo = setup_role_data["player_repo"]

    # Add a versatile player
    player_repo.add(discord_id=777, discord_username="AllRoles", initial_mmr=3500)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Insert match participations for all roles
    # We'll use existing match IDs
    for match_id in [1, 2, 3]:
        cursor.execute(
            """
            INSERT INTO match_participants
            (match_id, discord_id, team_number, won, side, lane_role)
            VALUES (?, ?, 1, 1, 'radiant', ?)
            """,
            (match_id, 777, match_id - 1),  # lane_role 0, 1, 2
        )

    conn.commit()

    # Query for this player
    cursor.execute(
        """
        SELECT
            lane_role,
            COUNT(*) as games,
            SUM(CASE WHEN won = 1 THEN 1 ELSE 0 END) as wins
        FROM match_participants
        WHERE discord_id = ? AND lane_role IS NOT NULL
        GROUP BY lane_role
        ORDER BY lane_role
        """,
        (777,),
    )

    results = cursor.fetchall()
    conn.close()

    # Should have 3 different roles
    assert len(results) == 3
    assert results[0][0] == 0  # Roaming
    assert results[1][0] == 1  # Safe Lane
    assert results[2][0] == 2  # Mid

    # All wins
    for result in results:
        assert result[2] == 1  # 1 win each


def test_rolewinrate_calculates_win_percentage(setup_role_data):
    """Test that win percentage calculation is accurate."""
    db_path = setup_role_data["db_path"]

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Get player 100's mid lane stats
    cursor.execute(
        """
        SELECT
            lane_role,
            COUNT(*) as games,
            SUM(CASE WHEN won = 1 THEN 1 ELSE 0 END) as wins
        FROM match_participants
        WHERE discord_id = ? AND lane_role = ?
        """,
        (100, 2),  # Mid lane
    )

    result = cursor.fetchone()
    conn.close()

    games = result[1]
    wins = result[2]
    win_rate = (wins / games * 100) if games > 0 else 0

    # Player 100 mid: 1W-1L = 50%
    assert games == 2
    assert wins == 1
    assert win_rate == 50.0
