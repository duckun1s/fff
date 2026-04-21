"""
╔══════════════════════════════════════════════════════════════════╗
║          HUMAN MADE SEAL — MOTEUR D'ANALYSE v4.0                 ║
║     Outil d'aide à la décision pour vérificateurs humains        ║
╚══════════════════════════════════════════════════════════════════╝

Aucune librairie externe. Python standard uniquement.
Ce script ne délivre PAS le label automatiquement.
Il produit un rapport d'indices pour les vérificateurs de l'association.
"""

import math
import re
import zlib
import json
import csv
import os
import hashlib
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from typing import Optional
from datetime import datetime
from enum import Enum


# ═══════════════════════════════════════════════════════════════════
#  TYPE DE CONTENU (détection automatique)
# ═══════════════════════════════════════════════════════════════════

class TypeContenu(Enum):
    TEXTE_COURT = "Texte court (< 150 mots)"
    TEXTE_LONG  = "Texte long  (> 150 mots)"
    CODE        = "Code source"
    MIXTE       = "Mixte (prose + code)"

    @staticmethod
    def detecter(texte: str, nb_mots: int) -> "TypeContenu":
        a_code  = bool(re.search(
            r'\bdef \b|\bclass \b|\bimport \b|#include|function\s*\(|<\?php|\bvar\b|\bconst\b|\blet\b',
            texte))
        a_prose = nb_mots > 40
        if a_code and a_prose:  return TypeContenu.MIXTE
        if a_code:              return TypeContenu.CODE
        if nb_mots < 150:       return TypeContenu.TEXTE_COURT
        return TypeContenu.TEXTE_LONG


# ═══════════════════════════════════════════════════════════════════
#  CONFIGURATION (seuils adaptés par type de contenu)
# ═══════════════════════════════════════════════════════════════════

@dataclass
class Seuils:
    compression:          float
    entropie:             float
    burstiness:           float
    ttr:                  float
    longueur_mots:        float
    ratio_phrases_courtes:float
    densite_virgules:     float
    ratio_hapax:          float
    repetition_ngram:     float
    diversite_debuts:     float
    densite_questions:    float
    densite_exclamations: float
    densite_parentheses:  float
    longueur_phrases:     float
    chiffres_ronds:       float
    sur_precision:        float
    diversite_emotionnelle:float
    densite_marqueurs:    float
    transitions_par_phrase:float
    longueur_paragraphes: float


SEUILS_PAR_TYPE: dict[TypeContenu, Seuils] = {
    TypeContenu.TEXTE_LONG: Seuils(
        compression=0.45,   entropie=5.0,      burstiness=6.0,
        ttr=0.72,           longueur_mots=5.2, ratio_phrases_courtes=0.15,
        densite_virgules=0.04, ratio_hapax=0.55, repetition_ngram=0.08,
        diversite_debuts=0.30, densite_questions=0.05, densite_exclamations=0.03,
        densite_parentheses=0.01, longueur_phrases=22.0, chiffres_ronds=0.6,
        sur_precision=0.02, diversite_emotionnelle=0.3, densite_marqueurs=1.5,
        transitions_par_phrase=0.25, longueur_paragraphes=80.0,
    ),
    TypeContenu.TEXTE_COURT: Seuils(
        compression=0.55,   entropie=4.5,      burstiness=4.0,
        ttr=0.80,           longueur_mots=5.0, ratio_phrases_courtes=0.10,
        densite_virgules=0.03, ratio_hapax=0.65, repetition_ngram=0.10,
        diversite_debuts=0.25, densite_questions=0.10, densite_exclamations=0.05,
        densite_parentheses=0.008, longueur_phrases=18.0, chiffres_ronds=0.5,
        sur_precision=0.015, diversite_emotionnelle=0.25, densite_marqueurs=2.0,
        transitions_par_phrase=0.30, longueur_paragraphes=50.0,
    ),
    TypeContenu.CODE: Seuils(
        compression=0.35,   entropie=4.0,      burstiness=8.0,
        ttr=0.65,           longueur_mots=6.0, ratio_phrases_courtes=0.40,
        densite_virgules=0.05, ratio_hapax=0.45, repetition_ngram=0.15,
        diversite_debuts=0.20, densite_questions=0.01, densite_exclamations=0.01,
        densite_parentheses=0.05, longueur_phrases=10.0, chiffres_ronds=0.7,
        sur_precision=0.03, diversite_emotionnelle=0.1, densite_marqueurs=0.5,
        transitions_par_phrase=0.10, longueur_paragraphes=30.0,
    ),
    TypeContenu.MIXTE: Seuils(
        compression=0.40,   entropie=4.8,      burstiness=7.0,
        ttr=0.70,           longueur_mots=5.5, ratio_phrases_courtes=0.20,
        densite_virgules=0.04, ratio_hapax=0.50, repetition_ngram=0.10,
        diversite_debuts=0.28, densite_questions=0.04, densite_exclamations=0.02,
        densite_parentheses=0.02, longueur_phrases=20.0, chiffres_ronds=0.65,
        sur_precision=0.025, diversite_emotionnelle=0.2, densite_marqueurs=1.2,
        transitions_par_phrase=0.20, longueur_paragraphes=60.0,
    ),
}

# Marqueurs sémantiques IA (80+)
MARQUEURS_IA = [
    # Transitions académiques
    "cependant","néanmoins","toutefois","en outre","par ailleurs","de plus",
    "ainsi","effectivement","certes","or","dès lors","de ce fait",
    "par conséquent","en revanche","à cet égard","à ce titre","à cet effet",
    # Introductions formelles
    "en conclusion","en résumé","pour conclure","en définitive",
    "en fin de compte","en somme","finalement","pour résumer",
    "il est important de","il est essentiel de","il convient de",
    "il est crucial de","il est fondamental de","il est nécessaire de",
    "il est primordial de","il est indispensable de",
    "il est à noter que","il faut souligner que",
    "il est intéressant de noter","notons que","soulignons que",
    # Hedging excessif
    "dans ce contexte","dans cette perspective","dans cette optique",
    "à la lumière de","au regard de","force est de constater",
    "il va sans dire","il est évident que","il est clair que",
    "sans aucun doute","indéniablement","incontestablement",
    # Mots-valises IA
    "crucial","fondamental","essentiel","primordial","capital","déterminant",
    "incontournable","indispensable","majeur","significatif","pertinent",
    "optimal","efficace","robuste","innovant","approfondi","exhaustif",
    "holistique","synergique","paradigme","écosystème","levier",
    # Formules de politesse IA
    "bien sûr","certainement","absolument","tout à fait","bien entendu",
    "avec plaisir","volontiers","n'hésitez pas","je vous invite à",
    # Structures de liste IA
    "premièrement","deuxièmement","troisièmement",
    "dans un premier temps","dans un second temps",
    "d'une part","d'autre part","en premier lieu","en second lieu",
    # Références vagues
    "comme mentionné précédemment","comme indiqué ci-dessus",
    "comme nous l'avons vu","il convient de rappeler","rappelons que",
    # Anglicismes formels souvent utilisés par les IA
    "framework","roadmap","stakeholder","synergy","leverage",
]

# Mots chargés émotionnellement (les humains en utilisent plus)
MOTS_EMOTIONNELS = [
    "adoré","détesté","furieux","ravi","terrifié","honteux","fier","nostalgique",
    "bouleversé","enchanté","épuisé","soulagé","énervé","excité","déprimé",
    "amoureux","jaloux","surpris","déçu","ému","angoissé","frustré","euphorique",
    "mélancolique","irrité","enthousiaste","abasourdi","mortifié","comblé",
    "effrayé","émerveillé","écœuré","gêné","attendri","révolté",
]

# Indicateurs d'authenticité humaine
MARQUEURS_HUMAINS = [
    # Hésitations / reformulations
    "enfin","bref","bon","voilà","quoi","hein","donc","alors","du coup",
    "genre","style","franchement","honnêtement","sincèrement","avoue",
    "en fait","je veux dire","c'est-à-dire","autrement dit",
    # Références personnelles
    "chez moi","selon moi","à mon avis","je pense que","je crois que",
    "j'ai l'impression","il me semble","personnellement","pour ma part",
    "dans mon cas","d'après mon expérience","de mon côté",
    # Anecdotes et spécificité
    "une fois","l'autre jour","hier","la semaine dernière","quand j'étais",
    "je me souviens","ça m'a rappelé","j'avais","je suis allé",
    # Incertitude naturelle
    "peut-être","probablement","sans doute","je ne suis pas sûr",
    "j'aurais tendance à","ça dépend","pas forcément","pas toujours",
]


# ═══════════════════════════════════════════════════════════════════
#  SIGNAL INDIVIDUEL
# ═══════════════════════════════════════════════════════════════════

@dataclass
class Signal:
    nom:         str
    valeur:      float
    seuil:       float
    signal_ia:   bool          # True = indice en faveur de l'IA
    poids:       int
    direction:   str           # "lt" ou "gt"
    explication: str           # Phrase lisible pour le vérificateur


# ═══════════════════════════════════════════════════════════════════
#  RAPPORT FINAL
# ═══════════════════════════════════════════════════════════════════

@dataclass
class Rapport:
    # Métadonnées
    timestamp:       str
    hash_texte:      str        # Empreinte du texte analysé
    nb_mots:         int
    nb_phrases:      int
    nb_paragraphes:  int
    type_contenu:    str
    fiabilite:       str        # Fiabilité de l'analyse (selon longueur)

    # Score
    score_ia:        int        # 0 = humain pur / 100 = IA certaine
    score_humain:    int
    signaux_ia:      list[str]
    signaux_humains: list[str]
    points_suspects: list[str]  # À vérifier manuellement
    details:         list[Signal]

    # Verdict pour le vérificateur
    recommandation:  str
    prochaines_etapes: list[str]


# ═══════════════════════════════════════════════════════════════════
#  ANALYSEUR DE MÉTRIQUES
# ═══════════════════════════════════════════════════════════════════

class Analyseur:

    def __init__(self, texte: str):
        self.texte_brut    = texte
        self.texte_propre  = texte.lower()
        # Mots alphabétiques uniquement (gère l'UTF-8 / accents)
        self.mots          = re.findall(r'\b[a-zA-ZÀ-ÿ]{2,}\b', self.texte_propre)
        self.phrases       = [p.strip() for p in re.split(r'[.!?\n]', texte) if len(p.strip()) > 3]
        self.paragraphes   = [p.strip() for p in texte.split('\n\n') if len(p.strip()) > 10]
        self.nb_mots       = len(self.mots)
        self.nb_phrases    = len(self.phrases)
        self.nb_paragraphes= max(1, len(self.paragraphes))

    # ── Statistiques de base ─────────────────────────────────────────

    def entropie_shannon(self) -> float:
        if not self.mots: return 0.0
        c = Counter(self.mots)
        n = len(self.mots)
        return -sum((f/n)*math.log2(f/n) for f in c.values())

    def ratio_compression(self) -> float:
        if not self.texte_brut: return 1.0
        raw = self.texte_brut.encode("utf-8")
        return len(zlib.compress(raw, level=9)) / len(raw)

    def burstiness(self) -> float:
        if len(self.phrases) < 2: return 0.0
        l = [len(p.split()) for p in self.phrases]
        m = sum(l)/len(l)
        return math.sqrt(sum((x-m)**2 for x in l)/len(l))

    def ttr(self) -> float:
        if not self.mots: return 0.0
        return len(set(self.mots)) / len(self.mots)

    def longueur_mots_moy(self) -> float:
        if not self.mots: return 0.0
        return sum(len(m) for m in self.mots) / len(self.mots)

    def ratio_phrases_courtes(self) -> float:
        if not self.phrases: return 0.0
        return sum(1 for p in self.phrases if len(p.split()) < 6) / len(self.phrases)

    def densite_virgules(self) -> float:
        if not self.texte_brut: return 0.0
        return self.texte_brut.count(",") / len(self.texte_brut)

    def ratio_hapax(self) -> float:
        if not self.mots: return 0.0
        c = Counter(self.mots)
        return sum(1 for f in c.values() if f == 1) / len(c)

    def repetition_ngram(self) -> float:
        if len(self.mots) < 4: return 0.0
        bg = [(self.mots[i], self.mots[i+1]) for i in range(len(self.mots)-1)]
        c  = Counter(bg)
        rep = sum(1 for f in c.values() if f > 1)
        return rep / len(c) if c else 0.0

    def diversite_debuts(self) -> float:
        debuts = [p.split()[0].lower() for p in self.phrases if p.split()]
        if not debuts: return 1.0
        c = Counter(debuts)
        n = len(debuts)
        ent = -sum((f/n)*math.log2(f/n) for f in c.values())
        return ent / math.log2(max(n, 2))

    def densite_questions(self) -> float:
        if not self.phrases: return 0.0
        return self.texte_brut.count("?") / len(self.phrases)

    def densite_exclamations(self) -> float:
        if not self.phrases: return 0.0
        return self.texte_brut.count("!") / len(self.phrases)

    def densite_parentheses(self) -> float:
        if not self.mots: return 0.0
        return self.texte_brut.count("(") / len(self.mots)

    def longueur_phrases_moy(self) -> float:
        if not self.phrases: return 0.0
        return sum(len(p.split()) for p in self.phrases) / len(self.phrases)

    # ── Nouvelles métriques avancées ─────────────────────────────────

    def ratio_chiffres_ronds(self) -> float:
        """
        Les IA adorent les chiffres ronds (10, 100, 50%).
        Ratio : chiffres ronds / total des nombres trouvés.
        """
        tous   = re.findall(r'\b\d+\b', self.texte_brut)
        if not tous: return 0.0
        ronds  = [n for n in tous if int(n) % 5 == 0 and int(n) > 0]
        return len(ronds) / len(tous)

    def ratio_sur_precision(self) -> float:
        """
        Les IA inventent des statistiques très précises (73,4%, 2,7 millions...).
        Détecte les nombres à virgule ou très précis dans un texte non-technique.
        """
        precis = re.findall(r'\b\d+[,\.]\d+\b|\b\d{6,}\b', self.texte_brut)
        return len(precis) / len(self.mots) if self.mots else 0.0

    def diversite_emotionnelle(self) -> float:
        """
        Les humains expriment des émotions variées et imprévisibles.
        Score = proportion de mots émotionnels distincts trouvés.
        """
        trouves = set(m for m in MOTS_EMOTIONNELS if m in self.texte_propre)
        return len(trouves) / len(MOTS_EMOTIONNELS)

    def densite_marqueurs_ia(self) -> float:
        if not self.mots: return 0.0
        compte = sum(1 for m in MARQUEURS_IA if m in self.texte_propre)
        return (compte / len(self.mots)) * 100

    def densite_marqueurs_humains(self) -> float:
        if not self.mots: return 0.0
        compte = sum(1 for m in MARQUEURS_HUMAINS if m in self.texte_propre)
        return (compte / len(self.mots)) * 100

    def transitions_par_phrase(self) -> float:
        """Ratio de phrases qui commencent par un connecteur logique."""
        connecteurs = {"cependant","néanmoins","toutefois","ainsi","or","donc",
                       "enfin","premièrement","deuxièmement","de plus","par ailleurs",
                       "en outre","certes","finalement","en conclusion","en résumé"}
        if not self.phrases: return 0.0
        debut_connecteur = sum(
            1 for p in self.phrases
            if p.split() and p.split()[0].lower().rstrip(',') in connecteurs
        )
        return debut_connecteur / len(self.phrases)

    def longueur_paragraphes_moy(self) -> float:
        """Les IA font des paragraphes bien calibrés et uniformes."""
        if not self.paragraphes: return 0.0
        return sum(len(p.split()) for p in self.paragraphes) / len(self.paragraphes)

    def variance_longueur_paragraphes(self) -> float:
        """Faible variance = paragraphes trop uniformes = signe d'IA."""
        if len(self.paragraphes) < 2: return 999.0
        l = [len(p.split()) for p in self.paragraphes]
        m = sum(l)/len(l)
        return math.sqrt(sum((x-m)**2 for x in l)/len(l))

    def ratio_majuscules_inattendues(self) -> float:
        """
        Les humains capitalisent parfois par emphase (VRAIMENT, JAMAIS).
        Les IA n'en font presque jamais hors titres.
        """
        mots_bruts = re.findall(r'\b[A-Z]{2,}\b', self.texte_brut)
        # Exclure les acronymes évidents (< 4 lettres)
        emphases = [m for m in mots_bruts if len(m) >= 4]
        return len(emphases) / len(self.mots) if self.mots else 0.0

    def ratio_contractions_familières(self) -> float:
        """
        C'est, j'ai, t'as, y'a, c'était... = langage oral humain.
        Les IA évitent ces contractions en prose formelle.
        """
        contractions = re.findall(
            r"\bc'(?:est|était|a|en)\b|\bj'(?:ai|avais|aime|aurais)\b"
            r"|\bt'(?:as|avais|aimes)\b|\by'a\b|\bqu'(?:il|elle|on)\b",
            self.texte_propre
        )
        return len(contractions) / len(self.mots) if self.mots else 0.0

    def ratio_repetitions_lexicales(self) -> float:
        """
        Un humain répète parfois un mot clé par insistance.
        L'IA répète des formules entières (trigrammes).
        """
        if len(self.mots) < 6: return 0.0
        tg = [(self.mots[i], self.mots[i+1], self.mots[i+2]) for i in range(len(self.mots)-2)]
        c  = Counter(tg)
        rep = sum(1 for f in c.values() if f > 1)
        return rep / len(c) if c else 0.0

    def score_uniformite_phrases(self) -> float:
        """
        Coefficient de variation des longueurs de phrases.
        Plus c'est bas, plus les phrases sont uniformes (signe d'IA).
        CV = écart-type / moyenne
        """
        if len(self.phrases) < 3: return 1.0
        l = [len(p.split()) for p in self.phrases]
        m = sum(l)/len(l)
        if m == 0: return 0.0
        et = math.sqrt(sum((x-m)**2 for x in l)/len(l))
        return et / m

    def densite_ponctuation_variee(self) -> float:
        """
        Les humains utilisent —, …, ;, : de façon variée et imprévisible.
        Les IA s'en tiennent surtout aux virgules et points.
        """
        signes_rares = len(re.findall(r'[—–…;]', self.texte_brut))
        total_ponct  = len(re.findall(r'[.,;:!?—–…]', self.texte_brut))
        if total_ponct == 0: return 0.0
        return signes_rares / total_ponct

    def presence_fautes_typiques(self) -> int:
        """
        Détecte les fautes / tics humains courants.
        Un humain en fait naturellement, l'IA presque jamais.
        """
        patterns = [
            r'\s{2,}',              # Double espace
            r'[,\.]{2,}',           # Double ponctuation
            r'\b(et|ou)\s*\1\b',    # Répétition "et et", "ou ou"
            r'[a-z][A-Z]',          # Majuscule interne accidentelle
        ]
        return sum(len(re.findall(p, self.texte_brut)) for p in patterns)

    def ratio_references_temporelles(self) -> float:
        """
        Les humains ancrent leurs textes dans le temps (hier, ce matin, en 2019...).
        Les IA restent vagues ou utilisent des dates génériques.
        """
        refs = re.findall(
            r'\b(hier|aujourd\'hui|demain|ce matin|ce soir|cette semaine|'
            r'ce mois|l\'an dernier|l\'année dernière|en \d{4}|depuis \d+|'
            r'il y a \d+|dans \d+ ans|lundi|mardi|mercredi|jeudi|vendredi)\b',
            self.texte_propre
        )
        return len(refs) / len(self.mots) if self.mots else 0.0

    def ratio_pronoms_premiere_personne(self) -> float:
        """
        Je, me, mon, ma, mes, moi = présence de l'auteur.
        Les IA évitent le 'je' en mode rédaction formelle.
        """
        pronoms = re.findall(
            r'\b(je|j\'|me|mon|ma|mes|moi|nous|notre|nos)\b',
            self.texte_propre
        )
        return len(pronoms) / len(self.mots) if self.mots else 0.0

    def ratio_interpellations(self) -> float:
        """
        Vous savez, tu vois, imagine que, pensez-y...
        Les humains interpellent leur lecteur de façon naturelle.
        """
        interpel = re.findall(
            r'\b(vous savez|tu vois|imaginez|pensez-y|croyez-moi|'
            r'avouez que|reconnaissez que|figure-toi|figurez-vous)\b',
            self.texte_propre
        )
        return len(interpel) / len(self.mots) if self.mots else 0.0

    def complexite_syntaxique(self) -> float:
        """
        Compte les subordonnées (que, qui, dont, lequel, laquelle...).
        Les IA surstructurent avec des relatives imbriquées.
        """
        subordonants = re.findall(
            r'\b(que|qui|dont|lequel|laquelle|lesquels|lesquelles|'
            r'auquel|duquel|où|quand|si|parce que|bien que|quoique)\b',
            self.texte_propre
        )
        return len(subordonants) / len(self.phrases) if self.phrases else 0.0

    # ── Analyse sémantique légère ─────────────────────────────────────

    def detecter_formules_clichees(self) -> list[str]:
        """Repère les formules ultra-typiques des IA."""
        cliches = [
            "il est important de noter", "dans un monde où", "à l'ère du numérique",
            "les défis sont nombreux", "force est de constater", "nul n'est besoin de",
            "il convient de souligner", "dans ce contexte en constante évolution",
            "en guise de conclusion", "pour faire face à ces défis",
            "il est crucial de comprendre", "une approche holistique",
            "les enjeux sont considérables", "il va sans dire que",
            "à bien des égards", "dans toute sa complexité",
            "sans prétendre à l'exhaustivité", "de manière significative",
            "dans une perspective globale", "au-delà des apparences",
        ]
        return [c for c in cliches if c in self.texte_propre]

    def detecter_marqueurs_humains_presents(self) -> list[str]:
        """Liste les marqueurs d'authenticité humaine trouvés."""
        return [m for m in MARQUEURS_HUMAINS if m in self.texte_propre]

    def detecter_mots_emotionnels_presents(self) -> list[str]:
        return [m for m in MOTS_EMOTIONNELS if m in self.texte_propre]


# ═══════════════════════════════════════════════════════════════════
#  MOTEUR DE SCORING
# ═══════════════════════════════════════════════════════════════════

class MoteurScoring:

    def __init__(self, analyseur: Analyseur, seuils: Seuils):
        self.a = analyseur
        self.s = seuils

    def _signal(self, nom, valeur, seuil, poids, direction, explication) -> Signal:
        signal_ia = (valeur < seuil) if direction == "lt" else (valeur > seuil)
        return Signal(nom=nom, valeur=valeur, seuil=seuil,
                      signal_ia=signal_ia, poids=poids,
                      direction=direction, explication=explication)

    def calculer(self) -> tuple[list[Signal], int, int]:
        a, s = self.a, self.s

        signaux = [
            # ── Métriques structurelles ──────────────────────────────
            self._signal("Compression zlib", a.ratio_compression(), s.compression, 12, "lt",
                "Structure trop répétitive — l'IA réutilise les mêmes n-grammes."),
            self._signal("Entropie Shannon", a.entropie_shannon(), s.entropie, 10, "lt",
                "Vocabulaire trop prévisible et optimisé."),
            self._signal("Burstiness", a.burstiness(), s.burstiness, 10, "lt",
                "Rythme métronomique — longueurs de phrases trop uniformes."),
            self._signal("Uniformité phrases (CV)", a.score_uniformite_phrases(), 0.40, 8, "lt",
                "Coefficient de variation faible — phrases toutes de taille similaire."),
            self._signal("Longueur phrases", a.longueur_phrases_moy(), s.longueur_phrases, 5, "gt",
                "Phrases longues et complexes — style rédactionnel IA."),
            self._signal("Variance paragraphes", a.variance_longueur_paragraphes(), 15.0, 5, "lt",
                "Paragraphes trop uniformes en longueur."),

            # ── Métriques lexicales ──────────────────────────────────
            self._signal("Type-Token Ratio", a.ttr(), s.ttr, 8, "gt",
                "Diversité lexicale artificiellement élevée."),
            self._signal("Longueur mots", a.longueur_mots_moy(), s.longueur_mots, 5, "gt",
                "Mots longs et formels — style académique forcé."),
            self._signal("Ratio hapax", a.ratio_hapax(), s.ratio_hapax, 6, "lt",
                "Peu de mots vraiment uniques — répétitions structurelles."),
            self._signal("Répétition bigrammes", a.repetition_ngram(), s.repetition_ngram, 6, "gt",
                "Séquences de 2 mots répétées — formules récurrentes."),
            self._signal("Répétition trigrammes", a.ratio_repetitions_lexicales(), 0.05, 5, "gt",
                "Séquences de 3 mots répétées — tournures figées."),

            # ── Métriques sémantiques ────────────────────────────────
            self._signal("Densité marqueurs IA", a.densite_marqueurs_ia(), s.densite_marqueurs, 8, "gt",
                "Forte densité de connecteurs logiques typiques d'IA."),
            self._signal("Transitions / phrase", a.transitions_par_phrase(), s.transitions_par_phrase, 5, "gt",
                "Trop de phrases qui commencent par un connecteur logique."),
            self._signal("Diversité débuts", a.diversite_debuts(), s.diversite_debuts, 5, "lt",
                "L'IA commence ses phrases avec les mêmes mots."),
            self._signal("Densité virgules", a.densite_virgules(), s.densite_virgules, 4, "gt",
                "Sur-utilisation des virgules — structuration artificielle."),
            self._signal("Densité parenthèses", a.densite_parentheses(), s.densite_parentheses, 3, "gt",
                "Trop de parenthèses — précisions bureaucratiques."),

            # ── Métriques comportementales ───────────────────────────
            self._signal("Phrases courtes", a.ratio_phrases_courtes(), s.ratio_phrases_courtes, 5, "lt",
                "Peu de phrases très courtes — manque d'impulsivité humaine."),
            self._signal("Questions", a.densite_questions(), s.densite_questions, 4, "lt",
                "Peu de questions — ton assertif non dialogique."),
            self._signal("Exclamations", a.densite_exclamations(), s.densite_exclamations, 3, "lt",
                "Absence d'exclamations — neutralité émotionnelle."),
            self._signal("Diversité émotionnelle", a.diversite_emotionnelle(), s.diversite_emotionnelle, 5, "lt",
                "Peu de mots chargés émotionnellement."),

            # ── Métriques d'authenticité ─────────────────────────────
            self._signal("Chiffres ronds", a.ratio_chiffres_ronds(), s.chiffres_ronds, 4, "gt",
                "Trop de chiffres ronds (10, 50, 100%) — imprécision IA."),
            self._signal("Sur-précision", a.ratio_sur_precision(), s.sur_precision, 3, "gt",
                "Statistiques inventées trop précises."),
            self._signal("Majuscules emphase", a.ratio_majuscules_inattendues(), 0.005, 3, "lt",
                "Aucune majuscule d'emphase — écriture trop normée."),
            self._signal("Contractions familières", a.ratio_contractions_familières(), 0.008, 4, "lt",
                "Absence de contractions orales (c'est, j'ai, t'as...)."),
            self._signal("Références temporelles", a.ratio_references_temporelles(), 0.005, 4, "lt",
                "Peu d'ancrage temporel concret."),
            self._signal("Pronoms 1ère personne", a.ratio_pronoms_premiere_personne(), 0.02, 4, "lt",
                "Peu de 'je/nous' — absence de voix personnelle."),
            self._signal("Ponctuation variée", a.densite_ponctuation_variee(), 0.10, 3, "lt",
                "Ponctuation pauvre (—, …, ; absents)."),
            self._signal("Interpellations lecteur", a.ratio_interpellations(), 0.003, 2, "lt",
                "Aucune interpellation directe du lecteur."),
            self._signal("Complexité syntaxique", a.complexite_syntaxique(), 3.5, 3, "gt",
                "Trop de subordonnées imbriquées — hypotaxe IA."),
            self._signal("Marqueurs humains", a.densite_marqueurs_humains(), 0.5, 5, "lt",
                "Aucun marqueur de langage naturel/oral détecté."),
        ]

        # Score IA (somme des poids déclenchés)
        score_ia = min(100, sum(sig.poids for sig in signaux if sig.signal_ia))

        # Score humain (bonus pour signaux positifs d'authenticité)
        bonus_humain = [
            ("Marqueurs humains présents",    a.densite_marqueurs_humains() > 0.5,   10),
            ("Émotions exprimées",            a.diversite_emotionnelle() > 0.05,      8),
            ("Pronoms personnels",            a.ratio_pronoms_premiere_personne() > 0.02, 7),
            ("Références temporelles",        a.ratio_references_temporelles() > 0.005, 6),
            ("Contractions orales",           a.ratio_contractions_familières() > 0.008, 6),
            ("Ponctuation variée",            a.densite_ponctuation_variee() > 0.15,  5),
            ("Fautes/tics humains",           a.presence_fautes_typiques() > 0,       5),
            ("Majuscules emphase",            a.ratio_majuscules_inattendues() > 0.005, 4),
            ("Interpellations",               a.ratio_interpellations() > 0.003,      4),
            ("Burstiness élevé",              a.burstiness() > 8.0,                   5),
        ]
        score_humain = min(100, sum(pts for _, cond, pts in bonus_humain if cond))

        return signaux, score_ia, score_humain


# ═══════════════════════════════════════════════════════════════════
#  GÉNÉRATEUR DE RAPPORT
# ═══════════════════════════════════════════════════════════════════

class GenerateurRapport:

    NIVEAUX_IA = [
        (85, "🔴 TRÈS PROBABLEMENT UNE IA",   "Refuser le label. Trop de signaux synthétiques."),
        (65, "🟠 PROBABLEMENT UNE IA",         "Approfondir la vérification manuelle."),
        (45, "🟡 AMBIGU — VÉRIFICATION REQUISE","Impossible de conclure. Enquête humaine obligatoire."),
        (25, "🟢 PROBABLEMENT HUMAIN",          "Vérification légère suffisante avant labellisation."),
        (0,  "🍃 TRÈS PROBABLEMENT HUMAIN",     "Candidat sérieux pour le label HUMAN MADE SEAL."),
    ]

    @staticmethod
    def _niveau(score_ia: int, score_humain: int) -> tuple[str, str]:
        # Bonus humain : si score_humain élevé, on atténue le score IA
        score_ajuste = max(0, score_ia - score_humain // 3)
        for seuil, label, conseils in GenerateurRapport.NIVEAUX_IA:
            if score_ajuste >= seuil:
                return label, conseils
        return GenerateurRapport.NIVEAUX_IA[-1][1], GenerateurRapport.NIVEAUX_IA[-1][2]

    @staticmethod
    def _fiabilite(nb_mots: int) -> str:
        if nb_mots < 50:   return "⚠ TRÈS FAIBLE (< 50 mots) — résultats indicatifs seulement"
        if nb_mots < 150:  return "⚠ FAIBLE (< 150 mots) — résultats à confirmer"
        if nb_mots < 500:  return "✓ CORRECTE (150–500 mots)"
        return "✓✓ ÉLEVÉE (> 500 mots)"

    @staticmethod
    def _prochaines_etapes(recommandation: str, score_ia: int) -> list[str]:
        etapes = []
        if score_ia > 65:
            etapes += [
                "Demander à l'auteur son processus de rédaction",
                "Rechercher le texte ou des extraits sur Google",
                "Comparer le style avec d'autres textes certifiés de l'auteur",
                "Soumettre à un second outil de détection (GPTZero, Originality.ai)",
            ]
        elif score_ia > 45:
            etapes += [
                "Entretien oral avec l'auteur sur le contenu",
                "Demander un brouillon ou notes préparatoires",
                "Vérifier l'historique de modification du document",
            ]
        else:
            etapes += [
                "Validation standard : vérifier l'identité de l'auteur",
                "Conservation du document source pour archivage",
            ]
        return etapes

    @classmethod
    def generer(cls, analyseur: Analyseur, signaux: list[Signal],
                score_ia: int, score_humain: int,
                type_contenu: TypeContenu) -> Rapport:

        a = analyseur
        niveau, conseils = cls._niveau(score_ia, score_humain)

        cliches   = a.detecter_formules_clichees()
        hum_marks = a.detecter_marqueurs_humains_presents()
        emo_marks = a.detecter_mots_emotionnels_presents()

        signaux_ia  = [sig.explication for sig in signaux if sig.signal_ia]
        signaux_hum = []
        if hum_marks:   signaux_hum.append(f"Marqueurs humains : {', '.join(hum_marks[:5])}")
        if emo_marks:   signaux_hum.append(f"Émotions exprimées : {', '.join(emo_marks[:5])}")
        if a.presence_fautes_typiques() > 0:
            signaux_hum.append("Tics/fautes humains détectés")

        points_suspects = []
        if cliches:
            points_suspects.append(f"Formules IA clichées : « {cliches[0]} »"
                                   + (f" (+ {len(cliches)-1} autres)" if len(cliches) > 1 else ""))
        if a.ratio_chiffres_ronds() > 0.7:
            points_suspects.append("Proportion anormalement élevée de chiffres ronds")
        if a.ratio_sur_precision() > 0.03:
            points_suspects.append("Statistiques très précises — à vérifier (sources ?)")
        if a.transitions_par_phrase() > 0.30:
            points_suspects.append("Début de phrases systématiquement structurés par connecteurs")
        if a.variance_longueur_paragraphes() < 8:
            points_suspects.append("Paragraphes d'une longueur suspecte uniformité")
        if not a.detecter_marqueurs_humains_presents():
            points_suspects.append("Absence totale de marqueurs de langage oral/naturel")

        hash_texte = hashlib.sha256(a.texte_brut.encode()).hexdigest()[:16]

        return Rapport(
            timestamp        = datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            hash_texte       = hash_texte,
            nb_mots          = a.nb_mots,
            nb_phrases       = a.nb_phrases,
            nb_paragraphes   = a.nb_paragraphes,
            type_contenu     = type_contenu.value,
            fiabilite        = cls._fiabilite(a.nb_mots),
            score_ia         = score_ia,
            score_humain     = score_humain,
            signaux_ia       = signaux_ia,
            signaux_humains  = signaux_hum,
            points_suspects  = points_suspects,
            details          = signaux,
            recommandation   = f"{niveau}\n  → {conseils}",
            prochaines_etapes= cls._prochaines_etapes(conseils, score_ia),
        )


# ═══════════════════════════════════════════════════════════════════
#  AFFICHAGE
# ═══════════════════════════════════════════════════════════════════

W = 64

def afficher_rapport(r: Rapport, verbeux: bool = True) -> None:
    sep   = "═" * W
    tiret = "─" * W

    print(f"\n{sep}")
    print(f"  ✦ HUMAN MADE SEAL — RAPPORT D'ANALYSE")
    print(f"  Horodatage : {r.timestamp}  |  Hash : {r.hash_texte}")
    print(sep)

    # ── Informations texte ────────────────────────────────────────────
    print(f"\n  TYPE         : {r.type_contenu}")
    print(f"  MOTS         : {r.nb_mots}  |  PHRASES : {r.nb_phrases}  |  PARAGRAPHES : {r.nb_paragraphes}")
    print(f"  FIABILITÉ    : {r.fiabilite}")

    # ── Jauges ───────────────────────────────────────────────────────
    print(f"\n  {tiret}")
    barre_ia  = "█" * (r.score_ia  // 5)
    barre_hum = "█" * (r.score_humain // 5)
    vide_ia   = "░" * (20 - r.score_ia  // 5)
    vide_hum  = "░" * (20 - r.score_humain // 5)
    print(f"  Score IA     [{barre_ia}{vide_ia}] {r.score_ia:3d}/100")
    print(f"  Score Humain [{barre_hum}{vide_hum}] {r.score_humain:3d}/100")

    # ── Tableau détaillé ─────────────────────────────────────────────
    if verbeux:
        print(f"\n  {'MÉTRIQUE':<32} {'VALEUR':>8}  {'SEUIL':>7}  SIGNAL")
        print(f"  {tiret}")
        for sig in r.details:
            icone = "⚠ IA" if sig.signal_ia else "  OK"
            print(f"  {sig.nom:<32} {sig.valeur:>8.4f}  {sig.seuil:>7.3f}  {icone}")

    # ── Signaux déclenchés ───────────────────────────────────────────
    print(f"\n  SIGNAUX IA DÉCLENCHÉS ({len(r.signaux_ia)}) :")
    print(f"  {tiret}")
    if r.signaux_ia:
        for s in r.signaux_ia:
            print(f"  ⚠  {s}")
    else:
        print("  Aucun signal IA.")

    print(f"\n  SIGNAUX HUMAINS DÉTECTÉS ({len(r.signaux_humains)}) :")
    print(f"  {tiret}")
    if r.signaux_humains:
        for s in r.signaux_humains:
            print(f"  ✓  {s}")
    else:
        print("  Aucun marqueur d'authenticité détecté.")

    # ── Points à vérifier ────────────────────────────────────────────
    if r.points_suspects:
        print(f"\n  POINTS À VÉRIFIER MANUELLEMENT :")
        print(f"  {tiret}")
        for p in r.points_suspects:
            print(f"  🔍  {p}")

    # ── Verdict ──────────────────────────────────────────────────────
    print(f"\n  {sep}")
    print(f"  VERDICT POUR LE VÉRIFICATEUR :")
    for ligne in r.recommandation.split("\n"):
        print(f"  {ligne}")

    print(f"\n  PROCHAINES ÉTAPES :")
    for i, e in enumerate(r.prochaines_etapes, 1):
        print(f"  {i}. {e}")

    print(f"  {sep}\n")


# ═══════════════════════════════════════════════════════════════════
#  EXPORT
# ═══════════════════════════════════════════════════════════════════

def exporter_json(r: Rapport, chemin: str) -> None:
    d = asdict(r)
    # Convertir les Signal en dict lisible
    d["details"] = [
        {"nom": s.nom, "valeur": round(s.valeur, 4), "seuil": s.seuil,
         "signal_ia": s.signal_ia, "poids": s.poids, "explication": s.explication}
        for s in r.details
    ]
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    print(f"  ✅ Export JSON : {chemin}")


def exporter_csv(r: Rapport, chemin: str) -> None:
    with open(chemin, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["metrique", "valeur", "seuil", "signal_ia", "poids", "explication"])
        for s in r.details:
            writer.writerow([s.nom, round(s.valeur, 4), s.seuil, s.signal_ia, s.poids, s.explication])
    print(f"  ✅ Export CSV  : {chemin}")


# ═══════════════════════════════════════════════════════════════════
#  HISTORIQUE DE SESSION
# ═══════════════════════════════════════════════════════════════════

class Session:
    def __init__(self):
        self.historique: list[Rapport] = []

    def ajouter(self, r: Rapport):
        self.historique.append(r)

    def afficher(self):
        if not self.historique:
            print("  Aucune analyse dans l'historique.\n")
            return
        print(f"\n  {'─'*55}")
        print(f"  HISTORIQUE ({len(self.historique)} analyse(s))")
        print(f"  {'─'*55}")
        for i, r in enumerate(self.historique, 1):
            niveau = r.recommandation.split("\n")[0].strip()
            print(f"  #{i:02d} IA={r.score_ia:3d}% HUM={r.score_humain:3d}%  [{r.timestamp}]")
            print(f"       {niveau}")
        print()

    def stats(self):
        if not self.historique:
            return
        scores   = [r.score_ia for r in self.historique]
        nb_ia    = sum(1 for r in self.historique if r.score_ia > 50)
        moy      = sum(scores) / len(scores)
        print(f"\n  STATS SESSION : {nb_ia} IA / {len(self.historique)-nb_ia} Humain(s)")
        print(f"  Score IA moyen : {moy:.1f}%\n")


# ═══════════════════════════════════════════════════════════════════
#  POINT D'ENTRÉE
# ═══════════════════════════════════════════════════════════════════

def lire_texte() -> str:
    print(f"\n  Collez le texte à analyser.")
    print(f"  (Tapez FIN sur une ligne seule pour lancer)\n")
    lignes = []
    while True:
        try:
            l = input()
        except EOFError:
            break
        if l.strip().upper() == "FIN":
            break
        lignes.append(l)
    return "\n".join(lignes).strip()


def menu_export(r: Rapport):
    print("\n  EXPORT DU RAPPORT :")
    print("  [1] JSON  [2] CSV  [3] Les deux  [4] Ignorer")
    choix = input("  Choix : ").strip()
    base  = f"HMS_{r.hash_texte}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    if choix in ("1","3"): exporter_json(r, f"{base}.json")
    if choix in ("2","3"): exporter_csv(r,  f"{base}.csv")


def main():
    session = Session()

    print(f"\n{'═'*64}")
    print(f"  ✦ HUMAN MADE SEAL — MOTEUR DE DÉTECTION v4.0")
    print(f"  30 métriques  |  80+ marqueurs  |  Python standard")
    print(f"{'═'*64}\n")

    while True:
        print("  [1] Analyser un texte")
        print("  [2] Analyser (mode silencieux — verdict seul)")
        print("  [3] Historique de session")
        print("  [4] Stats session")
        print("  [5] Quitter")
        choix = input("\n  Choix : ").strip()

        if choix in ("1", "2"):
            texte = lire_texte()
            if not texte:
                print("  ⚠ Aucun texte saisi.\n")
                continue

            analyseur    = Analyseur(texte)
            if analyseur.nb_mots < 20:
                print(f"  ⚠ Texte trop court ({analyseur.nb_mots} mots). Minimum : 20.\n")
                continue

            type_contenu = TypeContenu.detecter(texte, analyseur.nb_mots)
            seuils       = SEUILS_PAR_TYPE[type_contenu]
            moteur       = MoteurScoring(analyseur, seuils)
            signaux, score_ia, score_humain = moteur.calculer()
            rapport      = GenerateurRapport.generer(
                analyseur, signaux, score_ia, score_humain, type_contenu)

            afficher_rapport(rapport, verbeux=(choix == "1"))
            session.ajouter(rapport)
            menu_export(rapport)

        elif choix == "3":
            session.afficher()
        elif choix == "4":
            session.stats()
        elif choix == "5":
            print("\n  Au revoir.\n")
            break
        else:
            print("  Choix invalide.\n")


if __name__ == "__main__":
    main()
