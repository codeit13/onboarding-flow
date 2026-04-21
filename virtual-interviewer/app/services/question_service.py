from typing import List, Dict, Optional
from app.models.interview import ResumeData, JDData
from app.services.openai_service import OpenAIService


# ---------------------------------------------------------------------------
# Role detection + role-specific topic packs
# ---------------------------------------------------------------------------
#
# We want the AI Interview Agent to ask SHORT, role-specific questions —
# not generic 3-paragraph sales monologues. The team's previous prompt
# pushed the model toward 2-4 minute multi-part questions, which made the
# round feel like an essay exam. The Axis demo is a Branch Manager hire,
# so we (a) detect the role from the JD text and (b) feed the model a
# tight topic pack so the questions stay crisp and Branch-Manager-shaped.
# ---------------------------------------------------------------------------


_BRANCH_MANAGER_TOPICS = [
    "branch P&L and CASA growth targets",
    "leading a branch sales + service team",
    "cross-sell of liability, lending and wealth products",
    "audit, compliance and operational risk at the branch",
    "high-value customer relationships and escalations",
    "driving digital adoption and walk-in conversion",
]

_BDM_TOPICS = [
    "new client acquisition and pipeline build",
    "current account / liability book growth",
    "stakeholder management with operations and credit",
    "negotiation and pricing on commercial banking deals",
    "channel partnerships and lead sources",
    "field activity planning and weekly sales rhythm",
]

_GENERIC_SALES_TOPICS = [
    "recent quota attainment and pipeline health",
    "a deal you closed and one you lost",
    "stakeholder and objection handling",
    "field rhythm and prioritisation",
    "compliance / risk awareness",
]


def _detect_role(jd_text: str) -> str:
    """Return one of: 'branch_manager', 'bdm', 'generic'."""
    text = (jd_text or "").lower()
    if "branch manager" in text or "branch head" in text:
        return "branch_manager"
    if (
        "business development manager" in text
        or "bdm" in text
        or "relationship manager" in text
    ):
        return "bdm"
    return "generic"


def _topic_pack(role: str) -> List[str]:
    return {
        "branch_manager": _BRANCH_MANAGER_TOPICS,
        "bdm": _BDM_TOPICS,
        "generic": _GENERIC_SALES_TOPICS,
    }[role]


def _intro_question(role: str, language: str = "en") -> str:
    if language == "hi":
        if role == "branch_manager":
            return (
                "एक छोटा परिचय दीजिए — आपकी वर्तमान भूमिका, आपने कितनी बड़ी "
                "ब्रांच संभाली है, और आप इस Branch Manager पद में क्यों रुचि रखते हैं।"
            )
        if role == "bdm":
            return (
                "एक छोटा परिचय दीजिए — आपकी वर्तमान भूमिका, आप किस तरह के "
                "ग्राहकों को सेल करते हैं, और आप इस पद में क्यों रुचि रखते हैं।"
            )
        return (
            "एक छोटा परिचय दीजिए — आपकी वर्तमान भूमिका, आप क्या बेचते हैं, "
            "और आपने इस पद के लिए आवेदन क्यों किया।"
        )

    if role == "branch_manager":
        return (
            "Quick intro — your current role, branch size you've handled, "
            "and why this Branch Manager opening interests you."
        )
    if role == "bdm":
        return (
            "Quick intro — your current role, the kind of clients you sell to, "
            "and why this opening interests you."
        )
    return (
        "Quick intro — your current role, what you sell, and why you applied."
    )


def _fallback_questions(role: str, language: str = "en") -> List[str]:
    if language == "hi":
        if role == "branch_manager":
            return [
                _intro_question(role, "hi"),
                "आज आप जिस ब्रांच को संभालते हैं उसका साइज़ क्या है — बुक, टीम, रोज़ के walk-ins?",
                "पिछली तिमाही में आपने अपना CASA टारगेट कैसे पूरा किया, संक्षेप में बताइए।",
                "ब्रांच पर हुई किसी एक compliance या audit समस्या के बारे में बताइए।",
                "एक कमज़ोर relationship officer को आप कैसे coach करते हैं?",
            ]
        if role == "bdm":
            return [
                _intro_question(role, "hi"),
                "पिछली तिमाही में आपका टारगेट क्या था और आपने उसे कैसे हासिल किया?",
                "आपका field में एक सामान्य हफ़्ता कैसा होता है?",
                "ऐसा कोई deal जो आप हार गए — अब आप क्या अलग करते?",
                "आप कैसे तय करते हैं किन leads पर पहले काम करना है?",
            ]
        return [
            _intro_question(role, "hi"),
            "पिछली तिमाही में आपका टारगेट क्या था और आपने उसे कैसे पूरा किया?",
            "हाल ही में बंद किए एक deal के बारे में बताइए।",
            "किसी एक deal के बारे में बताइए जो आप हार गए।",
            "आप अपना हफ़्ता कैसे प्लान करते हैं?",
        ]

    if role == "branch_manager":
        return [
            _intro_question(role),
            "What's the size of the branch you run today — book, team, walk-ins per day?",
            "Walk me through how you hit your CASA target last quarter.",
            "Tell me about a compliance or audit issue you handled at the branch.",
            "How do you coach a low-performing relationship officer?",
        ]
    if role == "bdm":
        return [
            _intro_question(role),
            "What was your number last quarter and how did you land it?",
            "Walk me through your typical week in the field.",
            "Tell me about a deal you lost — what would you do differently?",
            "How do you decide which leads to chase first?",
        ]
    return [
        _intro_question(role),
        "What was your number last quarter and how did you hit it?",
        "Walk me through one deal you closed recently.",
        "Tell me about a deal you lost.",
        "How do you plan your week?",
    ]


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class QuestionService:
    def __init__(self):
        self.openai_service = OpenAIService()

    def generate_questions(
        self,
        resume_data: Optional[ResumeData] = None,
        jd_data: Optional[JDData] = None,
        question_count: int = 3,
        language: str = "en",
    ) -> List[Dict]:
        """Generate SHORT, role-specific interview questions.

        Style rules baked into the prompt:
        - Each question is one or at most two sentences (≤ 30 words).
        - Plain English, no jargon-stacking, no embedded sub-questions.
        - Tailored to the detected role (Branch Manager, BDM, or generic
          sales) using the topic pack defined above.
        - Answerable in 60–90 seconds — this is a screening interview,
          not a viva.
        """
        try:
            jd_text_for_role = (jd_data.content if jd_data else "") or ""
            role = _detect_role(jd_text_for_role)
            topics = _topic_pack(role)
            lang = (language or "en").lower()
            if lang not in ("en", "hi"):
                lang = "en"

            # Always include a short self-introduction as the first question
            questions = [{
                "id": 1,
                "question": _intro_question(role, lang),
                "answer": None,
                "is_mandatory": True
            }]

            remaining_questions = question_count - 1

            if lang == "hi":
                brevity_instruction = (
                    "STYLE RULES — these are non-negotiable:\n"
                    "1. हर सवाल एक वाक्य में हो, ज़्यादा से ज़्यादा दो। 30 शब्दों की सीमा।\n"
                    "2. कोई multi-part सवाल नहीं। कोई embedded follow-up नहीं।\n"
                    "3. साधारण बोलचाल की हिंदी — जैसे कोई असली banker फ़ोन पर बात कर रहा हो।\n"
                    "4. कैंडिडेट 60–90 सेकंड में जवाब दे सके।\n"
                    "5. भूमिका और कैंडिडेट के अनुभव से जुड़े सवाल हों — किताबी नहीं।\n"
                    "6. सवाल पूरी तरह देवनागरी हिंदी में लिखें — कोई English वाक्य नहीं। तकनीकी शब्द (CASA, KYC, branch) ज़रूरत होने पर इस्तेमाल कर सकते हैं।\n"
                )
            else:
                brevity_instruction = (
                    "STYLE RULES — these are non-negotiable:\n"
                    "1. Each question must be ONE sentence, at most TWO. Hard cap: 30 words.\n"
                    "2. No multi-part questions. No embedded follow-ups. No 'and / also / additionally'.\n"
                    "3. Plain conversational English — like a real interviewer talking, not a written exam.\n"
                    "4. The candidate should be able to answer in 60–90 seconds.\n"
                    "5. Be specific to the role and the candidate's background — never generic textbook prompts.\n"
                )

            role_label = {
                "branch_manager": "Axis Bank Branch Manager",
                "bdm": "Axis Bank Business Development Manager",
                "generic": "Axis Bank sales",
            }[role]

            topics_block = "\n".join(f"- {t}" for t in topics)

            if lang == "hi":
                prompt = (
                    f"आप एक {role_label} पद के लिए कैंडिडेट का स्क्रीनिंग इंटरव्यू कर रहे हैं। "
                    f"कुल {remaining_questions} छोटे और सटीक सवाल हिंदी में बनाइए। "
                    f"नीचे दिए गए topics में से एक-एक सवाल लीजिए (किसी भी क्रम में):\n"
                    f"{topics_block}\n\n"
                    f"{brevity_instruction}\n"
                    f"अगर resume में कोई ठोस आँकड़ा या अनुभव हो तो उसे स्वाभाविक रूप से reference कीजिए। "
                    f"कैंडिडेट से अपना परिचय देने को मत कहिए — वह सवाल पहले ही पूछा जा चुका है। "
                    f"सभी सवाल पूरी तरह देवनागरी हिंदी में होने चाहिए।"
                )
                system_msg = (
                    "आप Axis Bank के एक hiring manager हैं जो एक 5 मिनट का "
                    "स्क्रीनिंग इंटरव्यू कर रहे हैं। आप छोटे, सटीक, बोलचाल वाले "
                    "हिंदी सवाल पूछते हैं — कभी multi-part essay नहीं। हर सवाल "
                    "एक वाक्य में होता है जिसका जवाब 90 सेकंड में दिया जा सके। "
                    "आपकी भाषा वैसी होनी चाहिए जैसे कोई असली banker फ़ोन पर बात कर रहा हो।"
                )
            else:
                prompt = (
                    f"You are screening a candidate for an {role_label} role. "
                    f"Generate exactly {remaining_questions} short, sharp interview questions. "
                    f"Pick from these topic areas (one question per topic, in any order):\n"
                    f"{topics_block}\n\n"
                    f"{brevity_instruction}\n"
                    f"If the resume mentions concrete numbers or experiences, reference them naturally. "
                    f"Do NOT ask the candidate to introduce themselves — that question is already asked."
                )
                system_msg = (
                    "You are an Axis Bank hiring manager running a 5-minute "
                    "screening interview. You ask SHORT, specific, conversational "
                    "questions — never long multi-part essays. Each question is one "
                    "sentence the candidate can answer in under 90 seconds. You sound "
                    "like a real banker on a call, not a written exam paper."
                )

            generated_questions = self.openai_service.generate_interview_questions(
                resume_content=resume_data.content if resume_data else None,
                jd_content=jd_data.content if jd_data else None,
                num_questions=remaining_questions,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": prompt},
                ],
            )

            questions.extend([
                {
                    "id": i + 2,
                    "question": question,
                    "answer": None,
                    "is_mandatory": False
                }
                for i, question in enumerate(generated_questions)
            ])

            return questions

        except Exception:
            # Deterministic fallback — also short and role-specific.
            jd_text_for_role = (jd_data.content if jd_data else "") or ""
            role = _detect_role(jd_text_for_role)
            lang = (language or "en").lower()
            if lang not in ("en", "hi"):
                lang = "en"
            fallback = _fallback_questions(role, lang)[:question_count]
            return [
                {
                    "id": i + 1,
                    "question": q,
                    "answer": None,
                    "is_mandatory": i == 0,
                }
                for i, q in enumerate(fallback)
            ]
