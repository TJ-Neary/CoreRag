"""Tests for ConversationManager — multi-turn context-aware search."""

from src.search.conversation_manager import ConversationManager


class TestIsFollowUp:
    def test_short_query_is_follow_up(self):
        cm = ConversationManager()
        cm.add_turn("kubernetes deployment guide", [{"content": "result"}])
        assert cm._is_follow_up("what about scaling?") is True

    def test_pronoun_start_is_follow_up(self):
        cm = ConversationManager()
        cm.add_turn("python error handling", [])
        assert cm._is_follow_up("it keeps crashing") is True

    def test_connector_word_is_follow_up(self):
        cm = ConversationManager()
        cm.add_turn("react hooks", [])
        assert cm._is_follow_up("also how about context") is True

    def test_standalone_query_is_not_follow_up(self):
        cm = ConversationManager()
        assert cm._is_follow_up("kubernetes deployment guide") is False


class TestRewriteQuery:
    def test_rewrites_follow_up(self):
        cm = ConversationManager()
        cm.add_turn("kubernetes deployment troubleshooting", [])
        rewritten = cm.rewrite_query("what about scaling?")
        assert "kubernetes" in rewritten

    def test_no_rewrite_for_first_query(self):
        cm = ConversationManager()
        result = cm.rewrite_query("kubernetes deployment guide")
        assert result == "kubernetes deployment guide"

    def test_no_rewrite_for_standalone(self):
        cm = ConversationManager()
        cm.add_turn("python", [])
        result = cm.rewrite_query("a completely different topic about networking fundamentals")
        assert result == "a completely different topic about networking fundamentals"


class TestAddTurnAndPrune:
    def test_records_turns(self):
        cm = ConversationManager()
        cm.add_turn("query1", [{"content": "r1"}])
        cm.add_turn("query2", [{"content": "r2"}])
        assert len(cm._turns) == 2

    def test_auto_prunes(self):
        cm = ConversationManager(max_turns=3)
        for i in range(5):
            cm.add_turn(f"query{i}", [])
        assert len(cm._turns) == 3

    def test_clear(self):
        cm = ConversationManager()
        cm.add_turn("query", [])
        cm.clear()
        assert len(cm._turns) == 0


class TestContextSummary:
    def test_empty_context(self):
        cm = ConversationManager()
        assert cm.get_context_summary() == ""

    def test_shows_recent_queries(self):
        cm = ConversationManager()
        cm.add_turn("first query", [])
        cm.add_turn("second query", [])
        summary = cm.get_context_summary()
        assert "first query" in summary
        assert "second query" in summary
