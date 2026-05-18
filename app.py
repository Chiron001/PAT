import os, json, csv, io, statistics, base64
from datetime import datetime
from functools import wraps
from flask import Flask, request, jsonify, session, redirect, url_for, render_template, make_response
from flask_cors import CORS

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'fig-living-pat-2024-xK9mP2qR7v!')
CORS(app)

ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'FigLiving@2024')
DB_PATH = os.path.join(os.path.dirname(__file__), 'pat.db')
DATABASE_URL = os.environ.get('DATABASE_URL')  # set this on Vercel for persistent PostgreSQL

# ─── Database abstraction (SQLite locally, PostgreSQL on Vercel) ──────────────

class _Cur:
    """Uniform cursor wrapper: fetchone/fetchall always return plain dicts."""
    def __init__(self, cur, is_pg):
        self._c, self._pg = cur, is_pg

    def fetchone(self):
        row = self._c.fetchone()
        return dict(row) if row else None

    def fetchall(self):
        return [dict(r) for r in (self._c.fetchall() or [])]


class _Conn:
    """Use ? placeholders in all SQL — wrapper translates to %s for PostgreSQL."""
    def __init__(self):
        if DATABASE_URL:
            import psycopg2, psycopg2.extras
            url = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
            self._conn = psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)
            self._pg = True
        else:
            import sqlite3
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            self._conn = conn
            self._pg = False

    def execute(self, sql, params=()):
        if self._pg:
            import psycopg2
            sql = sql.replace('?', '%s')
            params = [psycopg2.Binary(p) if isinstance(p, (bytes, bytearray)) else p
                      for p in params]
            cur = self._conn.cursor()
            cur.execute(sql, params)
            return _Cur(cur, True)
        return _Cur(self._conn.execute(sql, params), False)

    def commit(self):  self._conn.commit()
    def close(self):   self._conn.close()


def get_db():
    return _Conn()

# ─── Questions & MBTI Data ────────────────────────────────────────────────────

QUESTIONS = [
    {"s":"Analytical depth","d":"A","q":"You are handed a month of FIG Living's sales data across Amazon, Shopify, and B2B channels. Your first instinct is to:","opts":[["Build a unified pivot table and look for patterns across all three channels before drawing any conclusions",4],["Focus on whichever channel drove the most revenue last month and dig deep into that",2],["Ask the team what they already believe is happening, then verify or refute it with data",3],["Quickly calculate top-line totals and flag anything that looks obviously off",1]]},
    {"s":"Analytical depth","d":"A","q":"A metric you track shows a 22% drop in conversion rate on the FIG Living website over 2 weeks. You:","opts":[["Segment by device, traffic source, landing page, and product category before saying anything",4],["Check if there was a price change or campaign launch first — those are the usual suspects",3],["Alert the team immediately so they can make quick decisions while you dig deeper",2],["Run a quick funnel analysis to see exactly where users are dropping off",4]]},
    {"s":"Analytical depth","d":"A","q":"When working with a large dataset, which statement best describes you?","opts":[["I naturally build validation checks and sanity-test my numbers before sharing",4],["I focus on getting directionally correct insights fast rather than perfect numbers",2],["I enjoy the exploration phase but find detailed cleaning and structuring tedious",1],["I always document my methodology so anyone can reproduce my analysis",3]]},
    {"s":"Analytical depth","d":"A","q":"FIG Living wants to forecast next quarter's D2C revenue. You would start by:","opts":[["Building a bottom-up model using SKU-level sell-through rates and traffic data",4],["Applying a growth percentage to last quarter's actuals based on known seasonality",2],["Researching how comparable D2C home décor brands forecast and adapting that approach",3],["Asking leadership what target they have in mind and working backwards",1]]},
    {"s":"Analytical depth","d":"A","q":"You notice two analyses from two team members give conflicting conclusions on the same data. You:","opts":[["Reconcile both analyses yourself by tracing the logic and assumptions in each",4],["Set up a quick meeting to understand each person's reasoning before deciding",3],["Go with the one that uses a more rigorous methodology",4],["Present both findings to the founder and let leadership decide",1]]},
    {"s":"Analytical depth","d":"A","q":"How do you typically handle uncertainty in your data?","opts":[["I quantify the uncertainty and include confidence ranges in my output",4],["I flag the gaps clearly and give my best estimate with caveats",3],["I gather more data before presenting anything incomplete",3],["I present what I have and note that assumptions may need revisiting",2]]},
    {"s":"Analytical depth","d":"A","q":"FIG Living is considering entering a new city for B2B sales. What analysis would you prioritize first?","opts":[["Market sizing: number of hotels, restaurants, and premium residences in the city",4],["Competitor mapping: which lighting brands are already active in that market",3],["Internal readiness: can we deliver and service orders there reliably",2],["ROI projection: what revenue and margin could we reasonably expect in year one",4]]},
    {"s":"Analytical depth","d":"A","q":"You are presenting analysis to FIG Living's founder. You realize mid-slide that one of your numbers may be slightly off. You:","opts":[["Pause, acknowledge it, and offer to revert with corrected data before conclusions are drawn",4],["Quickly calculate the likely impact and note it as a minor caveat while continuing",3],["Correct it on the spot if possible and explain what changed",3],["Continue the presentation and fix it quietly in the follow-up deck",1]]},
    {"s":"Analytical depth","d":"A","q":"Which best describes how you feel about building Excel or Google Sheets models?","opts":[["I genuinely enjoy it — structuring logic into a model is satisfying",4],["I can do it but prefer handing off the model-building to someone else once I define the structure",2],["I build functional models but rarely obsess over making them clean or scalable",2],["I build models that others can easily understand and update without my help",4]]},
    {"s":"Analytical depth","d":"A","q":"FIG Living's return rate increases by 3 percentage points in Q3. Your instinct is:","opts":[["This could be product quality, delivery damage, customer expectation mismatch, or seasonal — let me investigate all four",4],["Check customer feedback and support tickets first — the reason is usually hiding there",3],["Compare against industry benchmarks before deciding if this is actually a problem",3],["Map returns by SKU and channel to find the highest-concentration issue",4]]},
    {"s":"Aesthetic sensibility","d":"B","q":"You are reviewing the copy for a new FIG Living product page. The data says conversions are low but the description is factually accurate. You:","opts":[["Rewrite the copy to be more emotionally resonant — facts don't sell, feelings do",4],["A/B test two versions: one functional, one emotional — let data decide",3],["Flag it to the marketing team and share what the data shows",2],["Suggest adding lifestyle imagery to complement the existing copy",3]]},
    {"s":"Aesthetic sensibility","d":"B","q":"FIG Living is launching a new collection called Fold Series. You are asked to contribute to the naming of product variants. You:","opts":[["Research the visual and cultural references of 'fold' and propose names that carry that metaphor",4],["Suggest names that are easy to remember and search for",2],["Recommend naming conventions that are consistent with the existing product line",3],["Leave naming to the design/marketing team — my strength is in the numbers",1]]},
    {"s":"Aesthetic sensibility","d":"B","q":"When you walk into a beautifully designed room, what is your typical response?","opts":[["I immediately start noticing what makes it work — materials, proportions, light quality",4],["I notice that it feels good but couldn't immediately tell you why",2],["I appreciate it aesthetically but my mind quickly moves to other things",1],["I notice specific elements I'd want to replicate or avoid if I were designing a space",3]]},
    {"s":"Aesthetic sensibility","d":"B","q":"FIG Living is choosing between two presentation deck templates — one is clean and minimalist, the other is dense with data charts. You are presenting to an investor. You choose:","opts":[["The minimalist one — clarity and elegance signal brand confidence",4],["The data-heavy one — investors need proof points, not aesthetics",2],["A hybrid: lead with a clean narrative, then support with data appendix",4],["Whichever one the founder prefers",1]]},
    {"s":"Aesthetic sensibility","d":"B","q":"You are asked to review a proposed Instagram campaign for FIG Living. The creative looks beautiful but the targeting seems off. You:","opts":[["Flag both: the creative is strong but targeting will determine whether it works",4],["Focus on the targeting issue — that's what affects ROI",3],["Appreciate the creative quality and trust the marketing team knows their audience",1],["Ask to see the brief to understand whether the creative was meant for conversion or awareness",4]]},
    {"s":"Aesthetic sensibility","d":"B","q":"How important is it to you that the reports and dashboards you build look good?","opts":[["Very important — a well-designed report gets read and acted on. Ugly ones get ignored",4],["Somewhat important — functional first, aesthetics if time permits",2],["I'd rather spend that time on improving the analysis itself",1],["Important when presenting to external stakeholders, less so for internal use",3]]},
    {"s":"Aesthetic sensibility","d":"B","q":"FIG Living's brand identity is described as 'warm Scandinavian minimalism.' If you were briefing a junior analyst on what that means for how they present data, you would say:","opts":[["Less is more — show only what is necessary, use warm neutral tones, and leave white space",4],["Keep it professional and clean — nothing flashy",2],["Match the deck palette to FIG's brand colors",3],["I'd let the design team handle the visual brief",1]]},
    {"s":"Aesthetic sensibility","d":"B","q":"A new competitor has launched a premium lighting brand with stronger D2C aesthetics than FIG Living. Your reaction as a business analyst is:","opts":[["Conduct a full competitor audit: product range, price points, visual positioning, and customer sentiment",4],["Flag it to the team with a summary of what they're doing differently",3],["Track their pricing and promotions over the next quarter",2],["Note it and continue focusing on FIG Living's current priorities",1]]},
    {"s":"Aesthetic sensibility","d":"B","q":"Which of these projects would excite you most at FIG Living?","opts":[["Redesigning the product detail page to improve conversion using UX and copy insights",4],["Building a gross margin model across all SKUs to identify pricing opportunities",3],["Creating a demand forecasting tool to reduce stockouts",2],["Mapping the B2B sales pipeline and building a lead scoring model",3]]},
    {"s":"Aesthetic sensibility","d":"B","q":"You receive a brief to create a one-page report for FIG Living's board on business performance. You:","opts":[["Design it so every number tells a story and the visual hierarchy guides the reader's eye",4],["Include all key metrics with clear labels — completeness over design",2],["Use a standard business report template",1],["Write the content first, then think about layout and presentation",3]]},
    {"s":"Execution drive","d":"C","q":"FIG Living's founder asks you to have a market sizing analysis ready by tomorrow morning. It's 5 PM. You:","opts":[["Work through the evening — I'd rather deliver quality on time than ask for an extension",4],["Start immediately, identify the 20% of work that will give 80% of the answer, and deliver that",4],["Clarify what level of depth is actually needed before committing",3],["Scope it down, deliver a solid framework tonight, and offer to fill in tomorrow",3]]},
    {"s":"Execution drive","d":"C","q":"You have three urgent tasks from three different stakeholders all due on the same day. You:","opts":[["Prioritize by business impact and communicate clearly to all three about sequencing",4],["Ask each stakeholder to clarify urgency so I can sequence properly",3],["Handle the most complex one first to get it out of my head",2],["Do all three simultaneously and manage my time across them",2]]},
    {"s":"Execution drive","d":"C","q":"Which statement most accurately describes your relationship with deadlines?","opts":[["I treat deadlines as commitments — I will always find a way to deliver or flag early if I can't",4],["I work best under pressure — deadlines sharpen my focus",3],["I prefer to work steadily and not rush the quality of my output",2],["I communicate proactively if a deadline is at risk and always offer an updated timeline",4]]},
    {"s":"Execution drive","d":"C","q":"After delivering an analysis, you find a significant error in your model. You:","opts":[["Immediately inform the stakeholder, share the corrected version, and explain the impact of the change",4],["Fix it and send the updated version with a brief note about the correction",3],["Assess whether the error changes the conclusion before deciding to escalate",3],["Quietly update it and hope the error didn't affect any decisions yet",1]]},
    {"s":"Execution drive","d":"C","q":"You are building a monthly performance dashboard for FIG Living. Halfway through, you realize the data source is messy and will take 3 more days to clean. Deadline is tomorrow. You:","opts":[["Use cleaned data for the key metrics and flag that full data is pending — deliver something useful now",4],["Push for the deadline extension — better to deliver right than fast",2],["Build the dashboard structure and populate it with available data, noting gaps",4],["Escalate to your manager and ask for a decision on trade-offs",3]]},
    {"s":"Execution drive","d":"C","q":"How do you feel about starting tasks before you have all the information?","opts":[["Comfortable — I structure what I know, flag what I don't, and get started",4],["Somewhat comfortable — I need at least a clear output definition before I start",3],["Uncomfortable — I prefer clarity before investing effort",1],["Very comfortable — starting creates momentum and information gaps often fill themselves",4]]},
    {"s":"Execution drive","d":"C","q":"You finish your analysis two hours early. You:","opts":[["Use the time to stress-test your conclusions and look for holes in your logic",4],["Start on the next item in my queue",3],["Document your methodology clearly so others can build on it",3],["Take a break — deep work is tiring and rest improves future performance",2]]},
    {"s":"Execution drive","d":"C","q":"FIG Living is moving fast. New initiatives launch every 2-3 weeks. How do you feel about constantly shifting priorities?","opts":[["Energized — variety keeps me sharp and I adapt quickly",4],["Manageable — as long as there's clear communication and updated priorities",3],["Challenging — I work best when I can go deep on one thing",1],["Fine — I've learned to maintain parallel workstreams",3]]},
    {"s":"Execution drive","d":"C","q":"You've been asked to own a new project that is outside your current skillset. You:","opts":[["Accept it — I'll learn what I need to while doing it",4],["Accept it but carve out time upfront to develop the core skill I'm missing",4],["Ask if there's someone more suited and offer to support instead",2],["Accept it but set clear expectations about the learning curve",3]]},
    {"s":"Execution drive","d":"C","q":"How would your closest friend describe the way you work?","opts":[["Reliable and thorough — they always know I'll get it done and done well",4],["Creative and fast — I move quickly and figure things out along the way",3],["Thoughtful and careful — I take my time but the output is solid",2],["Flexible and collaborative — I work well with others and adjust to the team's rhythm",3]]},
    {"s":"Ambiguity tolerance","d":"D","q":"FIG Living has no formal job description for the BA role yet. You are the first hire. You feel:","opts":[["Excited — I get to define what good looks like",4],["Cautiously optimistic — I'll make it work but would prefer clearer expectations",3],["Somewhat anxious — I want to be evaluated against something fair",2],["Neutral — the work will define the role regardless of what's written",3]]},
    {"s":"Ambiguity tolerance","d":"D","q":"You are three weeks into your role and still don't have full data access. You:","opts":[["Work with what I have, document what I need, and escalate formally if the gap is blocking key work",4],["Keep asking every few days until I get access",3],["Find alternative data sources or proxies in the meantime",4],["Wait — I don't want to overstep by going around the process",1]]},
    {"s":"Ambiguity tolerance","d":"D","q":"The founder gives you a brief: 'I want to understand our customer.' No further guidance. You:","opts":[["Ask three clarifying questions, then structure a customer insight framework and present it for alignment",4],["Start exploring available data and customer feedback and return with a hypothesis",4],["Request more context — I want to be sure I'm solving the right problem",2],["Design a full customer research plan and present it for approval before starting",3]]},
    {"s":"Ambiguity tolerance","d":"D","q":"Which environment would you thrive in most?","opts":[["A fast startup where roles are fluid and I create my own structure",4],["A structured team where my responsibilities are clearly defined",1],["A hybrid — a growing company that's adding structure as it scales",3],["A company where I have clear KPIs but latitude in how I achieve them",4]]},
    {"s":"Ambiguity tolerance","d":"D","q":"FIG Living has conflicting data from two sources on the same metric. No one knows which is right. You:","opts":[["Triangulate using a third reference, document the discrepancy, and use the more conservative figure",4],["Escalate it — I won't present analysis built on data I don't trust",2],["Use the source that is more frequently used internally and note the issue",3],["Build parallel scenarios using both figures and show sensitivity",4]]},
    {"s":"Ambiguity tolerance","d":"D","q":"You're asked to present a recommendation to leadership but the evidence is 60/40, not conclusive. You:","opts":[["Present the recommendation clearly with the supporting evidence and quantify the risk of being wrong",4],["Present both sides and let leadership decide",2],["Gather more data before I'm willing to take a position",2],["Frame it as a hypothesis to be tested rather than a firm recommendation",3]]},
    {"s":"Ambiguity tolerance","d":"D","q":"A project you've been working on for 3 weeks is suddenly deprioritized. You:","opts":[["Document what I've done, archive it clearly, and redirect my energy",4],["Feel frustrated but move on quickly",3],["Ask for context on the reprioritization decision",3],["Use the freed time proactively to pick up something else useful",4]]},
    {"s":"Ambiguity tolerance","d":"D","q":"You are given access to FIG Living's full data stack with no specific task. What do you do?","opts":[["Explore freely and build a catalog of interesting insights and anomalies",4],["Ask what the team most needs answered right now",3],["Start with the highest-impact area (e.g. revenue or margins) and build from there",4],["Set up a data quality audit before diving into analysis",3]]},
    {"s":"Ambiguity tolerance","d":"D","q":"How do you handle situations where the 'right answer' doesn't exist?","opts":[["I'm comfortable taking a reasoned position and defending it with logic",4],["I prefer to reframe the question until a clearer answer emerges",3],["I feel uncomfortable — I need more structure to work effectively",1],["I document the tradeoffs and present options rather than a single answer",3]]},
    {"s":"Ambiguity tolerance","d":"D","q":"Your manager is often unavailable and you frequently need to make judgment calls. You feel:","opts":[["Empowered — autonomy is how I do my best work",4],["Fine — I'll make the call and flag it later",3],["Nervous — I want validation before I act on important decisions",1],["Comfortable — but I document my reasoning carefully",4]]},
    {"s":"Stakeholder orientation","d":"E","q":"FIG Living's marketing team disagrees with your analysis conclusion. You:","opts":[["Hear them out, understand their objection, and either update your view or explain why you stand by it",4],["Stand firm if I'm confident in the data — emotions shouldn't override evidence",2],["Explore whether we're answering the same question before deciding who's right",4],["Find a way to present both perspectives to the founder",2]]},
    {"s":"Stakeholder orientation","d":"E","q":"You need data from the operations team, but they're stretched thin. You:","opts":[["Understand their capacity constraints, prioritize what I truly need, and make it easy for them to help",4],["Escalate to my manager if I can't get what I need within a week",2],["Find workarounds to reduce my dependency on them",3],["Schedule a quick call to explain why this matters and what's at stake",4]]},
    {"s":"Stakeholder orientation","d":"E","q":"The founder asks you for a quick verbal update on category performance. You:","opts":[["Give a crisp two-sentence summary with the most important number and a recommendation",4],["Walk through the full analysis — I want them to see the nuance",2],["Ask what decision they're trying to make so I give them exactly what they need",4],["Share the top three highlights and offer to go deeper on any of them",3]]},
    {"s":"Stakeholder orientation","d":"E","q":"How do you prefer to communicate your analysis findings?","opts":[["Written first — I craft the narrative carefully before any verbal walkthrough",3],["Visual — I lead with charts and let the data speak",3],["Verbal — I explain the story first, then point to the data",2],["Adaptive — I match the format to what the stakeholder needs",4]]},
    {"s":"Stakeholder orientation","d":"E","q":"You notice that a senior team member is making a business decision based on an incorrect assumption. You:","opts":[["Respectfully raise it privately with clear evidence — being right isn't worth burning a relationship",4],["Raise it in the meeting — incorrect decisions hurt the business regardless of who's in the room",3],["Prepare a brief note with the correct data and share it after the meeting",3],["Wait to see if others catch it first",1]]},
    {"s":"Stakeholder orientation","d":"E","q":"How do you build trust with people you work with for the first time?","opts":[["By delivering on small commitments before asking for anything big",4],["By being transparent about my thinking and inviting pushback",3],["By understanding what they care about and making my work relevant to their goals",4],["By being responsive, reliable, and easy to work with",3]]},
    {"s":"Stakeholder orientation","d":"E","q":"FIG Living has a cross-functional meeting where tensions are high. Your analysis is at the center of the debate. You:","opts":[["Stay calm, present the data clearly, and help the team focus on the question rather than the conflict",4],["Let the leaders work it out — it's not my role to mediate",1],["Offer to walk through the methodology again so everyone is working from the same baseline",4],["Stay quiet and answer only direct questions",1]]},
    {"s":"Stakeholder orientation","d":"E","q":"You've built a great dashboard but no one is using it. You:","opts":[["Do a discovery conversation with users to understand the gap between what I built and what they need",4],["Redesign it based on what I think they actually want",2],["Schedule a walkthrough session to onboard people to the tool",3],["Escalate — if leadership doesn't prioritize data-driven decisions, I can't force it",1]]},
    {"s":"Stakeholder orientation","d":"E","q":"The founder asks you to validate a decision they've already made. You find the data doesn't support it. You:","opts":[["Share the data honestly and let them decide — my job is to inform, not please",4],["Soften the delivery but be clear about what the data shows",3],["Ask what they're trying to achieve — there may be a better path the data would support",4],["Present the data without a recommendation and let them draw conclusions",2]]},
    {"s":"Stakeholder orientation","d":"E","q":"How do you feel about presenting to leadership?","opts":[["Comfortable — I enjoy translating complexity into clarity for decision-makers",4],["Slightly nervous but I prepare thoroughly and usually do well",3],["I prefer written communication over live presentations",1],["It depends on how well I know the material — confidence drives comfort",3]]},
    {"s":"Growth mindset","d":"F","q":"You make a significant analytical error that leads to a wrong business decision. You:","opts":[["Own it fully, understand what went wrong, fix the output, and put a check in place to prevent recurrence",4],["Apologize sincerely and fix it as fast as possible",3],["Feel bad about it for a while but eventually move on",2],["Analyze why the error happened before deciding how to communicate it",3]]},
    {"s":"Growth mindset","d":"F","q":"You receive critical feedback on a report you put significant effort into. You:","opts":[["Listen carefully, ask clarifying questions, and revise with the feedback in mind",4],["Defend the parts I feel are correct and accept feedback on the parts I agree were weak",2],["Feel disappointed but use it as a learning moment",3],["Appreciate it — I actively want to know where I fell short",4]]},
    {"s":"Growth mindset","d":"F","q":"FIG Living is using tools you've never encountered before (Shopify analytics, Delhivery data, GoKwik). You:","opts":[["Figure it out independently — documentation and trial and error are my friends",4],["Ask a colleague for a quick orientation and then take it from there",3],["Request formal training or resources before using them in a live project",2],["Start exploring immediately and ask targeted questions as I go",4]]},
    {"s":"Growth mindset","d":"F","q":"Which of these statements best reflects your approach to learning?","opts":[["I seek out hard projects because that's where the learning happens",4],["I learn by doing — formal study is less effective than real problems",4],["I prefer structured learning first, then application",2],["I learn best from feedback — other people's perspective accelerates my growth",3]]},
    {"s":"Growth mindset","d":"F","q":"You're working in an area (e.g. D2C e-commerce) where you have limited prior experience. You:","opts":[["Immerse myself — read obsessively, talk to experts, and learn on the job",4],["Focus on applying transferable analytical skills and build domain knowledge gradually",3],["Feel challenged but motivated — I know I'll get there",3],["Prefer to work in areas where I already have domain context",1]]},
    {"s":"Growth mindset","d":"F","q":"How do you respond when a project fails to deliver the expected outcome?","opts":[["I run a retrospective — what did we assume, what did we miss, what would I do differently",4],["I feel frustrated but move forward — dwelling doesn't help",2],["I identify the root cause and ensure it doesn't happen again on my watch",4],["I take stock of my contribution and try to understand what I could have done differently",3]]},
    {"s":"Growth mindset","d":"F","q":"You are asked to mentor a junior analyst. You:","opts":[["Genuinely enjoy it — teaching makes me sharper and I care about people growing",4],["Do it if asked but it's not something I seek out",2],["Prefer to focus on my own work — mentoring is a time cost",1],["See it as part of the job and approach it with care and structure",3]]},
    {"s":"Growth mindset","d":"F","q":"What does 'career growth' mean to you?","opts":[["Increasing scope, impact, and autonomy — not just titles",4],["Building deep expertise in a domain I'm passionate about",3],["Financial progression and recognition for results",2],["Being given harder problems over time",4]]},
    {"s":"Growth mindset","d":"F","q":"FIG Living is a high-growth startup. Roles will evolve. How do you feel about that?","opts":[["Excited — I want my role to grow with the company",4],["Comfortable as long as growth is recognized and rewarded",3],["Somewhat uncertain — I prefer clarity on scope",1],["Ready — I've sought this kind of environment deliberately",4]]},
    {"s":"Growth mindset","d":"F","q":"Six months in, you feel you're not being stretched enough in your role. You:","opts":[["Proactively propose new projects or expanded scope to my manager",4],["Have an honest conversation about my ambitions and what it would take to grow",4],["Wait to see if opportunities arise naturally",1],["Look for ways to stretch within my current scope before escalating",3]]},
]

MBTI_TYPES = [
    {"type":"INTJ","name":"The Architect","fit":5,"dim":{"A":5,"B":3,"C":4,"D":5,"E":2,"F":4},"why":"Systematic, strategic, and deeply analytical. Natural model-builders who think long-term and challenge assumptions. Slight weakness in stakeholder warmth — needs coaching on communication style.","color":"#6366F1"},
    {"type":"INTP","name":"The Logician","fit":4,"dim":{"A":5,"B":4,"C":2,"D":4,"E":2,"F":3},"why":"Exceptional analytical thinkers with strong conceptual creativity. May underdeliver on execution speed and stakeholder management in fast D2C environment.","color":"#8B5CF6"},
    {"type":"ENTJ","name":"The Commander","fit":4,"dim":{"A":4,"B":3,"C":5,"D":5,"E":4,"F":4},"why":"Strong drivers with high execution energy. Natural leaders who can translate insight into action. May struggle to slow down for aesthetic nuance FIG Living requires.","color":"#6366F1"},
    {"type":"ENTP","name":"The Debater","fit":4,"dim":{"A":4,"B":5,"C":3,"D":5,"E":4,"F":5},"why":"Highly creative and cross-domain thinkers. Strong at connecting brand, data, and commerce. Can be inconsistent on follow-through — needs pairing with structure.","color":"#F59E0B"},
    {"type":"ISTJ","name":"The Logistician","fit":3,"dim":{"A":4,"B":2,"C":5,"D":2,"E":3,"F":3},"why":"Extremely reliable and thorough. Strong operations fit but may struggle with ambiguity and aesthetic demands of a D2C brand environment.","color":"#64748B"},
    {"type":"ISFJ","name":"The Defender","fit":2,"dim":{"A":3,"B":3,"C":4,"D":2,"E":5,"F":3},"why":"Warm, dependable, and stakeholder-focused. Better fit for CRM or customer success than analytical strategy at a design-led brand.","color":"#94A3B8"},
    {"type":"INFJ","name":"The Advocate","fit":3,"dim":{"A":3,"B":5,"C":3,"D":3,"E":4,"F":4},"why":"Deep aesthetic and empathetic intelligence. Strong brand intuition but may need analytical pairing to be effective in pure BA role.","color":"#EC4899"},
    {"type":"INFP","name":"The Mediator","fit":2,"dim":{"A":2,"B":5,"C":2,"D":3,"E":3,"F":4},"why":"High creative and aesthetic score, but low execution drive and structured analysis. Better fit for brand/content roles.","color":"#F472B6"},
    {"type":"ESTJ","name":"The Executive","fit":3,"dim":{"A":3,"B":2,"C":5,"D":3,"E":4,"F":3},"why":"Strong operators. Good for process-heavy BA work but FIG Living needs creative analytical thinkers, not just efficient ones.","color":"#64748B"},
    {"type":"ESFJ","name":"The Consul","fit":2,"dim":{"A":2,"B":3,"C":4,"D":2,"E":5,"F":3},"why":"Strong people orientation but limited fit for rigorous data-led BA work. Better suited to customer-facing or operations roles.","color":"#94A3B8"},
    {"type":"ISTP","name":"The Virtuoso","fit":3,"dim":{"A":4,"B":3,"C":4,"D":4,"E":2,"F":3},"why":"Technically capable and autonomous workers. Good with data tools. May struggle with strategic storytelling and stakeholder communication FIG needs.","color":"#64748B"},
    {"type":"ISFP","name":"The Adventurer","fit":2,"dim":{"A":2,"B":5,"C":2,"D":3,"E":3,"F":3},"why":"High aesthetic score, low analytical. FIG Living's BA role requires both — this type is better placed in product or visual design.","color":"#EC4899"},
    {"type":"ESTP","name":"The Entrepreneur","fit":3,"dim":{"A":3,"B":3,"C":5,"D":4,"E":4,"F":4},"why":"High energy, action-oriented, adaptive. Strong for fast execution but may lack depth in structured analytical thinking.","color":"#F59E0B"},
    {"type":"ENFP","name":"The Campaigner","fit":3,"dim":{"A":3,"B":5,"C":3,"D":4,"E":4,"F":5},"why":"Energetic, creative, and people-oriented. High aesthetic and growth mindset. Needs structure to channel into BA rigor. Consider for brand analytics hybrid roles.","color":"#F97316"},
]

# ─── Weights & Thresholds (FIG Living BA Role) ───────────────────────────────

DIM_WEIGHTS = {"A": 0.28, "C": 0.28, "F": 0.17, "D": 0.15, "E": 0.07, "B": 0.05}
DIM_LABELS  = {"A": "Analytical Depth", "B": "Aesthetic Sensibility", "C": "Execution Drive",
                "D": "Ambiguity Tolerance", "E": "Stakeholder Orientation", "F": "Growth Mindset"}
DIM_COLORS  = {"A": "#6366F1", "B": "#10B981", "C": "#F59E0B", "D": "#8B5CF6", "E": "#EC4899", "F": "#06B6D4"}

CRITICAL_DIMS = ["A", "C"]
CORE_DIMS     = ["F", "D"]
ENABLING_DIMS = ["E", "B"]

# ─── Database init ────────────────────────────────────────────────────────────

def init_db():
    conn = get_db()
    if conn._pg:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS submissions (
                id               SERIAL PRIMARY KEY,
                email            TEXT UNIQUE NOT NULL,
                name             TEXT,
                submitted_at     TIMESTAMP DEFAULT NOW(),
                time_taken_sec   INTEGER,
                answers_json     TEXT,
                dim_a            REAL, dim_b REAL, dim_c REAL,
                dim_d            REAL, dim_e REAL, dim_f REAL,
                overall_score    REAL,
                weighted_score   REAL,
                mbti_type        TEXT,
                mbti_name        TEXT,
                fit_rating       TEXT,
                recommendation   TEXT,
                narrative        TEXT,
                red_flags_json   TEXT,
                ip_address       TEXT,
                cv_filename      TEXT,
                cv_mimetype      TEXT,
                cv_data          BYTEA
            )
        """)
        for col, typ in [('cv_filename','TEXT'),('cv_mimetype','TEXT'),('cv_data','BYTEA')]:
            conn.execute(f"ALTER TABLE submissions ADD COLUMN IF NOT EXISTS {col} {typ}")
    else:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS submissions (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                email            TEXT UNIQUE NOT NULL,
                name             TEXT,
                submitted_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
                time_taken_sec   INTEGER,
                answers_json     TEXT,
                dim_a            REAL, dim_b REAL, dim_c REAL,
                dim_d            REAL, dim_e REAL, dim_f REAL,
                overall_score    REAL,
                weighted_score   REAL,
                mbti_type        TEXT,
                mbti_name        TEXT,
                fit_rating       TEXT,
                recommendation   TEXT,
                narrative        TEXT,
                red_flags_json   TEXT,
                ip_address       TEXT,
                cv_filename      TEXT,
                cv_mimetype      TEXT,
                cv_data          BLOB
            )
        """)
        for col, typ in [('cv_filename','TEXT'),('cv_mimetype','TEXT'),('cv_data','BLOB')]:
            try:
                conn.execute(f"ALTER TABLE submissions ADD COLUMN {col} {typ}")
            except Exception:
                pass
    conn.commit()
    conn.close()

init_db()

# ─── Scoring & Analytics ─────────────────────────────────────────────────────

def calc_dim_scores(answers):
    scores = {k: 0 for k in "ABCDEF"}
    counts = {k: 0 for k in "ABCDEF"}
    for i, q in enumerate(QUESTIONS):
        if i < len(answers) and answers[i] is not None:
            scores[q["d"]] += q["opts"][answers[i]][1]
            counts[q["d"]] += 1
    pct = {}
    for k in scores:
        pct[k] = round((scores[k] / (counts[k] * 4)) * 100) if counts[k] else 0
    return pct

def calc_weighted(pct):
    return round(sum(pct[k] * DIM_WEIGHTS[k] for k in DIM_WEIGHTS), 1)

def find_mbti(pct):
    best, best_score = None, -9999
    for m in MBTI_TYPES:
        s = sum(abs(pct[k] - m["dim"][k] * 20) for k in m["dim"])
        fit = m["fit"] * 10 - s * 0.1
        if fit > best_score:
            best_score, best = fit, m
    return best

def get_recommendation(pct, weighted):
    a, c = pct.get("A", 0), pct.get("C", 0)
    critical_floor = min(a, c)
    if weighted >= 74 and critical_floor >= 65:
        return "Strongly Recommended"
    if weighted >= 61 and critical_floor >= 52:
        return "Recommended"
    if weighted >= 48 and critical_floor >= 40:
        return "Consider with Caveats"
    return "Not Recommended"

def get_red_flags(pct):
    flags = []
    if pct.get("A", 0) < 45:
        flags.append(f"Critical deficit: Analytical Depth at {pct['A']}% — below minimum threshold of 45% for data-intensive BA work")
    if pct.get("C", 0) < 45:
        flags.append(f"Critical deficit: Execution Drive at {pct['C']}% — below threshold required for FIG Living's 2–3 week initiative cycle")
    if pct.get("A", 0) < 55 and pct.get("C", 0) < 55:
        flags.append("Dual critical concern: Both Analytical Depth and Execution Drive below 55% — core competency gap")
    if pct.get("D", 0) < 40:
        flags.append(f"Ambiguity Tolerance at {pct['D']}% signals difficulty navigating startup-stage uncertainty")
    if pct.get("F", 0) < 40:
        flags.append(f"Growth Mindset at {pct['F']}% — concerning for a role that requires continuous upskilling")
    return flags

def _dim_interp(dim, score):
    contexts = {
        "A": {
            "high": f"Analytical Depth at {score}% reflects rigorous, data-first thinking. Capable of multi-channel revenue analysis, pricing optimization, and demand forecasting at the depth FIG Living requires.",
            "mid":  f"Analytical Depth at {score}% is adequate. Can handle structured analysis with guidance, though may need support on complex multi-variable modelling.",
            "low":  f"Analytical Depth at {score}% falls below the 60% minimum for a role centred on commercial insight, SKU-level analysis, and forecasting. This is a critical gap.",
        },
        "C": {
            "high": f"Execution Drive at {score}% signals a strong bias to action — precisely what FIG Living's 2–3 week initiative cadence demands. Comfortable delivering under pressure without sacrificing quality.",
            "mid":  f"Execution Drive at {score}% suggests a steady, deliberate work style. Manageable in structured environments, but may need coaching for FIG Living's fast-paced delivery culture.",
            "low":  f"Execution Drive at {score}% raises serious concerns about delivery velocity. FIG Living's pace requires self-starters who can move from insight to output within tight timelines.",
        },
        "F": {
            "high": f"Growth Mindset at {score}% signals a candidate who actively seeks challenge, owns failure, and adapts fast — a non-negotiable for a first-of-its-kind BA role.",
            "mid":  f"Growth Mindset at {score}% shows reasonable openness to feedback and learning, though may need encouragement to proactively seek stretch assignments.",
            "low":  f"Growth Mindset at {score}% is below the expected baseline for a fast-scaling startup. This suggests resistance to change and potential friction in evolving role definitions.",
        },
        "D": {
            "high": f"Ambiguity Tolerance at {score}% confirms the candidate can operate with incomplete data and ambiguous briefs — essential in an environment where FIG Living is still building its data infrastructure.",
            "mid":  f"Ambiguity Tolerance at {score}% indicates a preference for some structure. Will thrive once processes are established but may need onboarding support in the early phase.",
            "low":  f"Ambiguity Tolerance at {score}% suggests discomfort with open-ended problems. As FIG Living's first BA hire, this candidate would face significant challenges in the role's setup phase.",
        },
        "E": {
            "high": f"Stakeholder Orientation at {score}% reflects a candidate who builds trust, communicates insights accessibly, and navigates cross-functional tension with maturity.",
            "mid":  f"Stakeholder Orientation at {score}% is functional. Can work across teams, though may benefit from coaching on influencing without authority.",
            "low":  f"Stakeholder Orientation at {score}% suggests a preference for independent work over cross-functional collaboration. Manageable in early stage but may create friction as team size grows.",
        },
        "B": {
            "high": f"Aesthetic Sensibility at {score}% demonstrates appreciation for brand language, visual communication, and design thinking — a differentiating asset at FIG Living's intersection of commerce and design.",
            "mid":  f"Aesthetic Sensibility at {score}% is sufficient. Will produce clean, functional outputs and appreciate brand context, without leading with creative thinking.",
            "low":  f"Aesthetic Sensibility at {score}% is below average. While not disqualifying for an analytical role, FIG Living's brand-centric culture values candidates who can bridge data and design.",
        },
    }
    level = "high" if score >= 68 else ("mid" if score >= 48 else "low")
    return contexts[dim][level]

def generate_narrative(row, rank, total, cohort_avg):
    pct = {"A": row["dim_a"], "B": row["dim_b"], "C": row["dim_c"],
           "D": row["dim_d"], "E": row["dim_e"], "F": row["dim_f"]}
    rec  = row["recommendation"]
    name = row["name"] or row["email"]
    ws   = row["weighted_score"]
    pctile = round((1 - (rank - 1) / max(total - 1, 1)) * 100)

    tier_open = {
        "Strongly Recommended": f"{name} ranks #{rank} of {total} candidates assessed — {pctile}th percentile — with a weighted fit score of {ws}%. This profile represents exceptional alignment with FIG Living's BA role requirements across both critical and core competencies.",
        "Recommended":          f"{name} ranks #{rank} of {total} candidates assessed (weighted fit: {ws}%, {pctile}th percentile). The profile demonstrates solid alignment with FIG Living's core BA requirements, with targeted development areas that are manageable given the right onboarding.",
        "Consider with Caveats": f"{name} ranks #{rank} of {total} (weighted fit: {ws}%, {pctile}th percentile). The profile shows potential in select dimensions but reveals meaningful gaps against FIG Living's critical competency thresholds. Conditional consideration subject to the caveats below.",
        "Not Recommended":      f"{name} ranks #{rank} of {total} (weighted fit: {ws}%, {pctile}th percentile). The profile falls below FIG Living's minimum competency thresholds across one or more critical dimensions. Not recommended for the BA role as currently defined.",
    }

    lines = [tier_open.get(rec, "")]
    lines.append("")
    lines.append("CRITICAL COMPETENCIES (56% of composite score)")
    lines.append(f"• {_dim_interp('A', pct['A'])}")
    lines.append(f"• {_dim_interp('C', pct['C'])}")
    lines.append("")
    lines.append("CORE COMPETENCIES (32% of composite score)")
    lines.append(f"• {_dim_interp('F', pct['F'])}")
    lines.append(f"• {_dim_interp('D', pct['D'])}")
    lines.append("")
    lines.append("ENABLING COMPETENCIES (12% of composite score)")
    lines.append(f"• {_dim_interp('E', pct['E'])}")
    lines.append(f"• {_dim_interp('B', pct['B'])}")
    lines.append("")

    # Cohort comparison
    above = [DIM_LABELS[k] for k in pct if pct[k] > cohort_avg.get(k, 50) + 8]
    below = [DIM_LABELS[k] for k in pct if pct[k] < cohort_avg.get(k, 50) - 8]
    if above:
        lines.append(f"COHORT DIFFERENTIATORS: Outperforms cohort average meaningfully in {', '.join(above)}.")
    if below:
        lines.append(f"COHORT GAPS: Trails cohort average meaningfully in {', '.join(below)}.")

    # Conclusion
    conclusions = {
        "Strongly Recommended": f"CONCLUSION: Proceed to interview. Priority-tier candidate. Focus interview on stakeholder communication depth and cross-functional collaboration scenarios.",
        "Recommended":          f"CONCLUSION: Recommended for interview. Probe execution pace under ambiguity and comfort with rapid context-switching during assessment.",
        "Consider with Caveats": f"CONCLUSION: Consider only if candidate pool is limited. Use interview to test whether demonstrated gaps are a pattern or assessement-specific outliers.",
        "Not Recommended":      f"CONCLUSION: Do not advance. Score falls below the minimum weighted threshold ({ws}% vs. 61% required). Reassess if role requirements change.",
    }
    lines.append(conclusions.get(rec, ""))
    return "\n".join(lines)

def compute_cohort_avg(students):
    if not students:
        return {k: 50 for k in "ABCDEF"}
    return {
        k: round(statistics.mean([s[f"dim_{k.lower()}"] for s in students]), 1)
        for k in "ABCDEF"
    }

# ─── Auth ─────────────────────────────────────────────────────────────────────

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin"):
            if request.is_json:
                return jsonify({"error": "Unauthorized"}), 401
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated

# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("assessment.html")

@app.route("/api/submit", methods=["POST"])
def submit():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400

    email       = (data.get("email") or "").strip().lower()
    name        = (data.get("name")  or "").strip()
    answers     = data.get("answers", [])
    time_s      = data.get("time_taken_sec", 0)
    cv_data_b64 = data.get("cv_data")
    cv_filename = data.get("cv_filename")
    cv_mimetype = data.get("cv_mimetype")

    if not email:
        return jsonify({"error": "Email is required"}), 400
    if len(answers) != 60:
        return jsonify({"error": "Incomplete submission"}), 400

    cv_blob = None
    if cv_data_b64:
        try:
            cv_blob = base64.b64decode(cv_data_b64)
        except Exception:
            cv_blob = None

    pct   = calc_dim_scores(answers)
    ws    = calc_weighted(pct)
    mbti  = find_mbti(pct)
    rec   = get_recommendation(pct, ws)
    flags = get_red_flags(pct)
    overall = round(sum(pct.values()) / 6, 1)

    conn = get_db()
    # Check if already submitted
    existing = conn.execute("SELECT id FROM submissions WHERE email=?", (email,)).fetchone()
    if existing:
        conn.close()
        return jsonify({"error": "This email has already submitted the assessment."}), 409

    # Calculate rank placeholder (will be updated lazily)
    all_students = [dict(r) for r in conn.execute("SELECT * FROM submissions").fetchall()]
    cohort_avg = compute_cohort_avg(all_students)
    temp_rank = len(all_students) + 1
    total     = temp_rank

    narrative_text = generate_narrative(
        {"name": name, "email": email, "dim_a": pct["A"], "dim_b": pct["B"],
         "dim_c": pct["C"], "dim_d": pct["D"], "dim_e": pct["E"], "dim_f": pct["F"],
         "weighted_score": ws, "recommendation": rec},
        temp_rank, total, cohort_avg
    )

    conn.execute("""
        INSERT INTO submissions
        (email, name, time_taken_sec, answers_json, dim_a, dim_b, dim_c, dim_d, dim_e, dim_f,
         overall_score, weighted_score, mbti_type, mbti_name, fit_rating, recommendation,
         narrative, red_flags_json, ip_address, cv_filename, cv_mimetype, cv_data)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        email, name, time_s, json.dumps(answers),
        pct["A"], pct["B"], pct["C"], pct["D"], pct["E"], pct["F"],
        overall, ws,
        mbti["type"], mbti["name"],
        ("Strong Fit" if overall >= 75 else "Good Fit" if overall >= 62 else "Partial Fit" if overall >= 48 else "Developmental"),
        rec, narrative_text, json.dumps(flags),
        request.remote_addr, cv_filename, cv_mimetype, cv_blob
    ))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

# ─── Admin Routes ─────────────────────────────────────────────────────────────

@app.route("/admin")
@admin_required
def admin_dashboard():
    return render_template("admin/dashboard.html")

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        pw = request.form.get("password", "")
        if pw == ADMIN_PASSWORD:
            session["admin"] = True
            session.permanent = True
            return redirect(url_for("admin_dashboard"))
        error = "Invalid password. Try again."
    return render_template("admin/login.html", error=error)

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("admin_login"))

@app.route("/api/admin/overview")
@admin_required
def api_overview():
    conn = get_db()
    students = [dict(r) for r in conn.execute("SELECT * FROM submissions ORDER BY weighted_score DESC").fetchall()]
    conn.close()

    if not students:
        return jsonify({"total": 0, "avg_weighted": 0, "rec_dist": {}, "dim_avgs": {}, "timeline": [], "mbti_dist": {}})

    total = len(students)
    avg_w = round(statistics.mean([s["weighted_score"] for s in students]), 1)
    avg_o = round(statistics.mean([s["overall_score"] for s in students]), 1)

    rec_dist = {}
    for s in students:
        rec_dist[s["recommendation"]] = rec_dist.get(s["recommendation"], 0) + 1

    dim_avgs = {k: round(statistics.mean([s[f"dim_{k.lower()}"] for s in students]), 1) for k in "ABCDEF"}

    mbti_dist = {}
    for s in students:
        mbti_dist[s["mbti_type"]] = mbti_dist.get(s["mbti_type"], 0) + 1

    # Timeline (submissions per day)
    tl = {}
    for s in students:
        day = s["submitted_at"][:10] if s["submitted_at"] else "unknown"
        tl[day] = tl.get(day, 0) + 1
    timeline = [{"date": d, "count": c} for d, c in sorted(tl.items())]

    # Dimension stats
    dim_stats = {}
    for k in "ABCDEF":
        vals = [s[f"dim_{k.lower()}"] for s in students]
        dim_stats[k] = {
            "avg": round(statistics.mean(vals), 1),
            "min": min(vals), "max": max(vals),
            "std": round(statistics.stdev(vals), 1) if len(vals) > 1 else 0,
            "label": DIM_LABELS[k], "color": DIM_COLORS[k]
        }

    return jsonify({
        "total": total, "avg_weighted": avg_w, "avg_overall": avg_o,
        "rec_dist": rec_dist, "dim_avgs": dim_avgs, "dim_stats": dim_stats,
        "mbti_dist": mbti_dist, "timeline": timeline,
        "strongly_rec": rec_dist.get("Strongly Recommended", 0),
        "not_rec": rec_dist.get("Not Recommended", 0),
    })

@app.route("/api/admin/candidates")
@admin_required
def api_candidates():
    conn = get_db()
    rows = conn.execute("""
        SELECT id, email, name, submitted_at, time_taken_sec,
               dim_a, dim_b, dim_c, dim_d, dim_e, dim_f,
               overall_score, weighted_score, mbti_type, mbti_name,
               fit_rating, recommendation, narrative, red_flags_json,
               ip_address, cv_filename
        FROM submissions ORDER BY weighted_score DESC
    """).fetchall()
    conn.close()
    students = []
    for rank, r in enumerate(rows, 1):
        s = dict(r)
        s["rank"] = rank
        s["red_flags"] = json.loads(s.get("red_flags_json") or "[]")
        s["has_cv"] = bool(s.get("cv_filename"))
        del s["red_flags_json"]
        students.append(s)
    return jsonify(students)

@app.route("/api/admin/candidate/<int:sid>")
@admin_required
def api_candidate(sid):
    conn = get_db()
    row = conn.execute("""
        SELECT id, email, name, submitted_at, time_taken_sec,
               dim_a, dim_b, dim_c, dim_d, dim_e, dim_f,
               overall_score, weighted_score, mbti_type, mbti_name,
               fit_rating, recommendation, narrative, red_flags_json,
               answers_json, ip_address, cv_filename
        FROM submissions WHERE id=?
    """, (sid,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Not found"}), 404
    s = dict(row)
    s["red_flags"]  = json.loads(s.get("red_flags_json") or "[]")
    s["answers"]    = json.loads(s.get("answers_json") or "[]")
    s["has_cv"]     = bool(s.get("cv_filename"))
    del s["answers_json"], s["red_flags_json"]
    return jsonify(s)

@app.route("/api/admin/candidate/<int:sid>", methods=["DELETE"])
@admin_required
def delete_candidate(sid):
    conn = get_db()
    row = conn.execute("SELECT id FROM submissions WHERE id=?", (sid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Not found"}), 404
    conn.execute("DELETE FROM submissions WHERE id=?", (sid,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/admin/cv/<int:sid>")
@admin_required
def admin_cv(sid):
    conn = get_db()
    row = conn.execute("SELECT cv_data, cv_filename, cv_mimetype FROM submissions WHERE id=?", (sid,)).fetchone()
    conn.close()
    if not row or not row["cv_data"]:
        return jsonify({"error": "No CV uploaded for this candidate"}), 404
    response = make_response(bytes(row["cv_data"]))
    response.headers["Content-Type"] = row["cv_mimetype"] or "application/octet-stream"
    response.headers["Content-Disposition"] = f'inline; filename="{row["cv_filename"] or "cv"}"'
    return response

@app.route("/api/admin/export/csv")
@admin_required
def export_csv():
    conn = get_db()
    rows = [dict(r) for r in conn.execute("SELECT * FROM submissions ORDER BY weighted_score DESC").fetchall()]
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    headers = ["Rank","Name","Email","Submitted At","Time Taken (min)","Recommendation",
               "Weighted Score","Overall Score","Analytical Depth","Aesthetic Sensibility",
               "Execution Drive","Ambiguity Tolerance","Stakeholder Orientation","Growth Mindset",
               "MBTI Type","MBTI Name","Fit Rating","Red Flags","CV Uploaded","IP Address"]
    writer.writerow(headers)
    for rank, s in enumerate(rows, 1):
        flags = json.loads(s.get("red_flags_json") or "[]")
        writer.writerow([
            rank, s["name"], s["email"], s["submitted_at"],
            round((s["time_taken_sec"] or 0) / 60, 1),
            s["recommendation"], s["weighted_score"], s["overall_score"],
            s["dim_a"], s["dim_b"], s["dim_c"], s["dim_d"], s["dim_e"], s["dim_f"],
            s["mbti_type"], s["mbti_name"], s["fit_rating"],
            " | ".join(flags), "Yes" if s.get("cv_filename") else "No", s["ip_address"]
        ])

    response = make_response(output.getvalue())
    response.headers["Content-Disposition"] = f'attachment; filename="fig_living_pat_{datetime.now().strftime("%Y%m%d_%H%M")}.csv"'
    response.headers["Content-Type"] = "text/csv"
    return response

@app.route("/api/admin/export/json")
@admin_required
def export_json():
    conn = get_db()
    rows = [dict(r) for r in conn.execute("SELECT * FROM submissions ORDER BY weighted_score DESC").fetchall()]
    conn.close()
    for s in rows:
        s["red_flags"] = json.loads(s.get("red_flags_json") or "[]")
        s["answers"]   = json.loads(s.get("answers_json")   or "[]")
        del s["red_flags_json"], s["answers_json"]
    response = make_response(json.dumps(rows, indent=2, default=str))
    response.headers["Content-Disposition"] = f'attachment; filename="fig_living_pat_{datetime.now().strftime("%Y%m%d_%H%M")}.json"'
    response.headers["Content-Type"] = "application/json"
    return response

@app.route("/api/admin/export/narratives")
@admin_required
def export_narratives():
    conn = get_db()
    rows = [dict(r) for r in conn.execute("SELECT * FROM submissions ORDER BY weighted_score DESC").fetchall()]
    conn.close()
    lines = ["FIG LIVING — PERSONALITY ASSESSMENT TOOL", "Candidate Narrative Report", "=" * 60, ""]
    for rank, s in enumerate(rows, 1):
        lines.append(f"#{rank} | {s['name']} | {s['email']}")
        lines.append(f"Weighted Score: {s['weighted_score']}% | Recommendation: {s['recommendation']}")
        lines.append("-" * 60)
        lines.append(s.get("narrative") or "No narrative generated.")
        lines.append("")
        lines.append("=" * 60)
        lines.append("")
    response = make_response("\n".join(lines))
    response.headers["Content-Disposition"] = f'attachment; filename="fig_living_narratives_{datetime.now().strftime("%Y%m%d_%H%M")}.txt"'
    response.headers["Content-Type"] = "text/plain; charset=utf-8"
    return response

# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("  FIG Living P.A.T — Starting server")
    print("  Student test  →  http://localhost:5000/")
    print("  Admin panel   →  http://localhost:5000/admin")
    app.run(debug=False, host="0.0.0.0", port=5000)
