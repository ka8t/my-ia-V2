"""
Tests pour le service d'indexation de recherche.

Execution: docker-compose exec app python -m pytest tests/crypto/test_search_index.py -v
"""
import pytest

from app.common.crypto.search import SearchIndexService


class TestSearchIndexService:
    """Tests pour SearchIndexService."""

    @pytest.fixture
    def service(self, test_hmac_key: bytes) -> SearchIndexService:
        """Instance du service avec clé de test."""
        return SearchIndexService(hmac_key=test_hmac_key)

    # ===== Tests Blind Index =====

    def test_blind_index_deterministic(self, service: SearchIndexService):
        """Même valeur produit toujours le même blind index."""
        value = "test@example.com"
        index1 = service.create_blind_index(value)
        index2 = service.create_blind_index(value)

        assert index1 == index2
        assert len(index1) == 64  # SHA256 en hex

    def test_blind_index_case_insensitive(self, service: SearchIndexService):
        """Le blind index ignore la casse."""
        index_lower = service.create_blind_index("test@example.com")
        index_upper = service.create_blind_index("TEST@EXAMPLE.COM")
        index_mixed = service.create_blind_index("Test@Example.Com")

        assert index_lower == index_upper == index_mixed

    def test_blind_index_removes_accents(self, service: SearchIndexService):
        """Le blind index ignore les accents."""
        index1 = service.create_blind_index("éàüç")
        index2 = service.create_blind_index("eauc")

        assert index1 == index2

    def test_blind_index_normalizes_spaces(self, service: SearchIndexService):
        """Le blind index normalise les espaces."""
        index1 = service.create_blind_index("Jean  Dupont")
        index2 = service.create_blind_index("Jean Dupont")
        index3 = service.create_blind_index("  Jean   Dupont  ")

        assert index1 == index2 == index3

    def test_blind_index_empty_string(self, service: SearchIndexService):
        """Blind index d'une chaîne vide retourne chaîne vide."""
        assert service.create_blind_index("") == ""

    def test_blind_index_different_values_differ(self, service: SearchIndexService):
        """Valeurs différentes produisent des blind index différents."""
        index1 = service.create_blind_index("value1")
        index2 = service.create_blind_index("value2")

        assert index1 != index2

    def test_blind_index_different_keys_differ(self, test_hmac_key: bytes):
        """Clés différentes produisent des blind index différents."""
        service1 = SearchIndexService(hmac_key=test_hmac_key)

        other_key = bytes.fromhex("F" * 64)
        service2 = SearchIndexService(hmac_key=other_key)

        value = "same-value"
        assert service1.create_blind_index(value) != service2.create_blind_index(value)

    # ===== Tests Trigrammes =====

    def test_create_trigrams_basic(self, service: SearchIndexService):
        """Génère les trigrammes d'un mot simple."""
        trigrams = service.create_trigrams("paris")

        assert trigrams == {"par", "ari", "ris"}

    def test_create_trigrams_case_insensitive(self, service: SearchIndexService):
        """Les trigrammes ignorent la casse."""
        trigrams1 = service.create_trigrams("Paris")
        trigrams2 = service.create_trigrams("PARIS")
        trigrams3 = service.create_trigrams("paris")

        assert trigrams1 == trigrams2 == trigrams3

    def test_create_trigrams_removes_accents(self, service: SearchIndexService):
        """Les trigrammes ignorent les accents."""
        trigrams1 = service.create_trigrams("Éléphant")
        trigrams2 = service.create_trigrams("elephant")

        assert trigrams1 == trigrams2

    def test_create_trigrams_too_short(self, service: SearchIndexService):
        """Valeur trop courte retourne ensemble vide."""
        assert service.create_trigrams("ab") == set()
        assert service.create_trigrams("a") == set()
        assert service.create_trigrams("") == set()

    def test_create_trigrams_exactly_three(self, service: SearchIndexService):
        """Valeur de 3 caractères retourne un trigramme."""
        trigrams = service.create_trigrams("abc")
        assert trigrams == {"abc"}

    def test_create_trigrams_ignores_spaces(self, service: SearchIndexService):
        """Les trigrammes ne contiennent pas d'espaces."""
        trigrams = service.create_trigrams("a b c d e")

        # Aucun trigramme ne doit contenir d'espace
        for tg in trigrams:
            assert " " not in tg

    def test_create_trigrams_multiword(self, service: SearchIndexService):
        """Trigrammes d'une phrase avec plusieurs mots."""
        trigrams = service.create_trigrams("Jean Dupont")

        # Vérifie quelques trigrammes attendus
        assert "jea" in trigrams
        assert "ean" in trigrams
        assert "dup" in trigrams
        assert "ont" in trigrams

    # ===== Tests Index Trigrammes =====

    def test_create_trigram_index(self, service: SearchIndexService):
        """Crée un index de trigrammes hashés."""
        index = service.create_trigram_index("paris")

        # Format: liste de hashes
        assert isinstance(index, list)

        # Chaque hash fait 16 caractères
        for h in index:
            assert len(h) == 16

        # 3 trigrammes pour "paris"
        assert len(index) == 3

    def test_create_trigram_index_empty(self, service: SearchIndexService):
        """Index de trigrammes vide pour valeur courte."""
        assert service.create_trigram_index("ab") == []
        assert service.create_trigram_index("") == []

    def test_create_trigram_index_deterministic(self, service: SearchIndexService):
        """Même valeur produit le même index."""
        index1 = service.create_trigram_index("Marseille")
        index2 = service.create_trigram_index("marseille")

        assert index1 == index2

    # ===== Tests Correspondance Trigrammes =====

    def test_match_trigrams_exact(self, service: SearchIndexService):
        """Correspondance exacte des trigrammes."""
        stored = service.create_trigram_index("Paris")
        assert service.match_trigrams("paris", stored) is True

    def test_match_trigrams_partial(self, service: SearchIndexService):
        """Correspondance partielle (début du mot)."""
        stored = service.create_trigram_index("Marseille")

        # "mars" est contenu dans "marseille"
        assert service.match_trigrams("mars", stored) is True
        assert service.match_trigrams("marse", stored) is True

    def test_match_trigrams_substring(self, service: SearchIndexService):
        """Correspondance d'une sous-chaîne."""
        stored = service.create_trigram_index("Montpellier")

        # "pell" est au milieu
        assert service.match_trigrams("pell", stored) is True

    def test_match_trigrams_no_match(self, service: SearchIndexService):
        """Pas de correspondance."""
        stored = service.create_trigram_index("Paris")

        assert service.match_trigrams("lyon", stored) is False
        assert service.match_trigrams("berlin", stored) is False

    def test_match_trigrams_query_too_short(self, service: SearchIndexService):
        """Requête trop courte retourne False."""
        stored = service.create_trigram_index("Paris")

        assert service.match_trigrams("pa", stored) is False
        assert service.match_trigrams("p", stored) is False

    def test_match_trigrams_empty(self, service: SearchIndexService):
        """Valeurs vides retournent False."""
        assert service.match_trigrams("", "abc") is False
        assert service.match_trigrams("abc", "") is False
        assert service.match_trigrams("", "") is False

    # ===== Tests Score de Recherche =====

    def test_search_score_perfect_match(self, service: SearchIndexService):
        """Score parfait pour correspondance exacte."""
        stored = service.create_trigram_index("paris")
        score = service.search_score("paris", stored)

        assert score == 1.0

    def test_search_score_partial_match(self, service: SearchIndexService):
        """Score partiel pour correspondance partielle."""
        stored = service.create_trigram_index("marseille")
        score = service.search_score("mars", stored)

        # "mars" a 2 trigrammes, tous présents dans "marseille"
        assert score == 1.0

    def test_search_score_no_match(self, service: SearchIndexService):
        """Score zéro pour aucune correspondance."""
        stored = service.create_trigram_index("paris")
        score = service.search_score("lyon", stored)

        assert score == 0.0

    def test_search_score_some_match(self, service: SearchIndexService):
        """Score intermédiaire pour correspondance partielle."""
        stored = service.create_trigram_index("parisien")
        score = service.search_score("parix", stored)

        # "parix" vs "parisien" - certains trigrammes communs
        assert 0.0 < score < 1.0


class TestNormalization:
    """Tests pour la normalisation des valeurs."""

    @pytest.fixture
    def service(self, test_hmac_key: bytes) -> SearchIndexService:
        return SearchIndexService(hmac_key=test_hmac_key)

    def test_normalize_preserves_alphanumeric(self, service: SearchIndexService):
        """Les caractères alphanumériques sont préservés."""
        # Utilise blind_index comme proxy pour tester la normalisation
        idx1 = service.create_blind_index("abc123")
        idx2 = service.create_blind_index("ABC123")

        assert idx1 == idx2

    def test_normalize_removes_punctuation(self, service: SearchIndexService):
        """La ponctuation est supprimée."""
        idx1 = service.create_blind_index("hello-world")
        idx2 = service.create_blind_index("hello.world")
        idx3 = service.create_blind_index("helloworld")

        assert idx1 == idx2 == idx3

    def test_normalize_handles_special_chars(self, service: SearchIndexService):
        """Les caractères spéciaux sont gérés."""
        idx1 = service.create_blind_index("test@example.com")
        idx2 = service.create_blind_index("testexamplecom")

        assert idx1 == idx2

    def test_normalize_phone_number(self, service: SearchIndexService):
        """Les numéros de téléphone sont normalisés."""
        # La normalisation supprime la ponctuation mais garde les espaces normalisés
        idx1 = service.create_blind_index("+33 6 12 34 56 78")
        idx2 = service.create_blind_index("33 6 12 34 56 78")  # Sans le +
        idx3 = service.create_blind_index("06.12.34.56.78")
        idx4 = service.create_blind_index("0612345678")

        # +33 devient 33 (+ supprimé), mais les espaces restent normalisés
        assert idx1 == idx2
        # Les points sont supprimés, donc 06.12... = 0612...
        assert idx3 == idx4
        # 06... est différent de 33...
        assert idx3 != idx1
