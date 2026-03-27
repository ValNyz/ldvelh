"""
Tests unitaires pour extraction_service.py
Focus sur ExtractionResult (logique pure, pas d'I/O)
"""

from services.extraction_service import ExtractionResult


class TestExtractionResult:
    """Tests pour ExtractionResult dataclass"""

    def test_default_values(self):
        """Valeurs par défaut"""
        result = ExtractionResult()
        assert result.segment_summary == ""
        assert result.facts == []
        assert result.entities_created == []
        assert result.gauge_changes == []
        assert result.inventory_changes == []

    def test_to_dict(self):
        """Conversion en dict"""
        result = ExtractionResult(
            segment_summary="Valentin explore le bar",
            facts=[{"fact_type": "observation", "content": "Le bar est vide"}],
            gauge_changes=[{"gauge": "energie", "delta": -1}],
        )
        d = result.to_dict()

        assert d["segment_summary"] == "Valentin explore le bar"
        assert len(d["facts"]) == 1
        assert d["facts"][0]["fact_type"] == "observation"
        assert d["gauge_changes"][0]["delta"] == -1

    def test_to_dict_all_keys(self):
        """to_dict contient toutes les clés"""
        result = ExtractionResult()
        d = result.to_dict()

        expected_keys = [
            "segment_summary",
            "facts",
            "entities_created",
            "entities_updated",
            "objects_created",
            "relations_created",
            "relations_updated",
            "gauge_changes",
            "credit_transactions",
            "inventory_changes",
            "commitments_created",
            "commitments_resolved",
            "events_scheduled",
        ]
        for key in expected_keys:
            assert key in d


class TestExtractionResultMerge:
    """Tests pour ExtractionResult.merge()"""

    def test_merge_lists(self):
        """Merge étend les listes"""
        result = ExtractionResult(
            facts=[{"id": 1}],
            entities_created=[{"name": "Alice"}],
        )
        result.merge(
            {
                "facts": [{"id": 2}, {"id": 3}],
                "entities_created": [{"name": "Bob"}],
            }
        )

        assert len(result.facts) == 3
        assert len(result.entities_created) == 2
        assert result.entities_created[1]["name"] == "Bob"

    def test_merge_string(self):
        """Merge remplace les strings non vides"""
        result = ExtractionResult(segment_summary="Initial")
        result.merge({"segment_summary": "Updated"})
        assert result.segment_summary == "Updated"

    def test_merge_empty_string_ignored(self):
        """String vide ne remplace pas"""
        result = ExtractionResult(segment_summary="Initial")
        result.merge({"segment_summary": ""})
        assert result.segment_summary == "Initial"

    def test_merge_unknown_keys_ignored(self):
        """Clés inconnues ignorées"""
        result = ExtractionResult()
        result.merge({"unknown_key": "value", "another": [1, 2, 3]})
        assert not hasattr(result, "unknown_key")

    def test_merge_multiple_partial_results(self):
        """Merge plusieurs résultats partiels"""
        result = ExtractionResult()

        # Phase 1: résumé + état protagoniste
        result.merge(
            {
                "segment_summary": "Valentin entre dans le bar",
                "gauge_changes": [{"gauge": "energie", "delta": -1}],
            }
        )

        # Phase 2: entités
        result.merge(
            {
                "entities_created": [{"name": "Marie", "entity_type": "pnj"}],
            }
        )

        # Phase 3: faits + relations
        result.merge(
            {
                "facts": [{"fact_type": "observation"}],
                "relations_created": [{"source": "Valentin", "target": "Marie"}],
            }
        )

        assert result.segment_summary == "Valentin entre dans le bar"
        assert len(result.gauge_changes) == 1
        assert len(result.entities_created) == 1
        assert len(result.facts) == 1
        assert len(result.relations_created) == 1

    def test_merge_inventory_changes(self):
        """Merge des changements d'inventaire"""
        result = ExtractionResult()
        result.merge(
            {
                "inventory_changes": [
                    {"action": "acquire", "object_hint": "clé magnétique"},
                    {"action": "lose", "object_ref": "crédits"},
                ]
            }
        )

        assert len(result.inventory_changes) == 2
        assert result.inventory_changes[0]["action"] == "acquire"
        assert result.inventory_changes[1]["action"] == "lose"

    def test_merge_credit_transactions(self):
        """Merge des transactions de crédits"""
        result = ExtractionResult()
        result.merge(
            {
                "credit_transactions": [
                    {"amount": -50, "description": "Achat boisson"},
                ]
            }
        )
        result.merge(
            {
                "credit_transactions": [
                    {"amount": 100, "description": "Récompense"},
                ]
            }
        )

        assert len(result.credit_transactions) == 2
        total = sum(t["amount"] for t in result.credit_transactions)
        assert total == 50

    def test_merge_commitments(self):
        """Merge des engagements"""
        result = ExtractionResult()
        result.merge(
            {
                "commitments_created": [{"commitment_type": "promise", "to": "Marie"}],
                "commitments_resolved": [{"ref": "old_promise"}],
                "events_scheduled": [{"title": "RDV", "planned_cycle": 5}],
            }
        )

        assert len(result.commitments_created) == 1
        assert len(result.commitments_resolved) == 1
        assert len(result.events_scheduled) == 1


class TestExtractionResultEdgeCases:
    """Tests des cas limites"""

    def test_merge_none_values(self):
        """Merge avec None dans les valeurs"""
        result = ExtractionResult(facts=[{"id": 1}])
        # Ne devrait pas planter
        result.merge({"facts": None})
        # facts reste inchangé car None n'est pas une liste
        assert len(result.facts) == 1

    def test_merge_with_nested_data(self):
        """Merge avec données imbriquées"""
        result = ExtractionResult()
        result.merge(
            {
                "relations_created": [
                    {
                        "relation": {
                            "source_ref": "Valentin",
                            "target_ref": "Marie",
                            "relation_type": "knows",
                        },
                        "cycle": 1,
                    }
                ]
            }
        )

        assert result.relations_created[0]["relation"]["source_ref"] == "Valentin"
