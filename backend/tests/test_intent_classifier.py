"""Unit tests for intent classification."""

from orchestrator_agent.orchestrator import IntentClassifier


class TestIntentClassifier:
    def setup_method(self):
        self.classifier = IntentClassifier()

    def test_research_intent(self):
        assert self.classifier.classify_fast("Research AI trends") == "research"

    def test_code_intent(self):
        assert self.classifier.classify_fast("Implement a REST API") == "code"

    def test_write_intent(self):
        assert self.classifier.classify_fast("Write a blog post") == "write"

    def test_analyze_intent(self):
        assert self.classifier.classify_fast("Analyze sales data") == "analyze"

    def test_summarize_intent(self):
        assert self.classifier.classify_fast("Summarize this report") == "summarize"

    def test_ambiguous_defaults_to_research(self):
        assert self.classifier.classify_fast("Hello world") == "research"
