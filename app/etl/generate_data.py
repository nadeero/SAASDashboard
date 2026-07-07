"""
app/etl/generate_data.py

Synthetic B2B SaaS sales dataset generator.

DESIGN DECISION: We deliberately do NOT depend on the `Faker` library.
Reasons:
  1. One fewer external dependency in a project that's meant to be easy
     to clone and run offline.
  2. Faker's generic name/company data doesn't encode SaaS-specific
     realism (industries, deal size bands by company size, stage
     progression logic). We get more realistic *sales* data by hand-
     curating small vocabularies and layering real sales-motion logic
     on top (see below) than by using generic fake-data libraries.

DESIGN DECISION: The generator is *seeded* (random.seed(SEED)) so the
dataset is reproducible -- anyone cloning the repo gets the exact same
"company" to demo against, which matters for a portfolio piece (screenshots,
demo videos, and README numbers all stay in sync run after run).

REALISM LOGIC BUILT INTO THE GENERATOR (this is the part that makes the
dataset useful for analytics, not just random noise):

  - Company size drives deal value: Enterprise accounts get bigger deals
    than SMB accounts (log-normal distribution per band), mirroring real
    ACV (annual contract value) patterns.
  - Stage distribution is realistic funnel-shaped: opportunities created
    further back in time have had a chance to close; recent opportunities
    are more likely still open. We simulate this by picking created_date
    first, then probabilistically "aging" the opportunity through the
    funnel based on how much time has elapsed since creation.
  - Win rate varies by sales rep (some reps are simply better) and by
    company size (SMB deals close faster / at a higher rate than complex
    Enterprise deals), which is what makes the "rep leaderboard" analytics
    meaningful instead of flat noise.
  - Activities are generated per-opportunity in proportion to deal
    complexity: bigger deals and later-stage deals accumulate more
    touchpoints, matching real sales-engagement patterns.
"""

import random
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

from app.models import (
    SalesRep,
    Account,
    Contact,
    Opportunity,
    Activity,
    STAGE_CHOICES,
    OPEN_STAGES,
)

SEED = 42

TODAY = date(2026, 7, 1)  # fixed "as-of" date so the dataset is reproducible
DATASET_START = TODAY - relativedelta(years=3)  # 3 years of history

# ---------------------------------------------------------------------------
# Curated vocabularies
# ---------------------------------------------------------------------------

REGIONS = ["West", "East", "Central", "EMEA", "APAC"]

FIRST_NAMES = [
    "Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Jamie", "Cameron",
    "Priya", "Wei", "Fatima", "Diego", "Sofia", "Noah", "Emma", "Liam",
    "Olivia", "Ethan", "Ava", "Mason", "Isabella", "Lucas", "Mia", "Aiden",
    "Grace", "Nathan", "Chloe", "Ryan", "Zoe", "Marcus", "Nina", "Omar",
]
LAST_NAMES = [
    "Kim", "Patel", "Garcia", "Chen", "Nguyen", "Smith", "Johnson", "Williams",
    "Brown", "Martinez", "Davis", "Lopez", "Wilson", "Anderson", "Thomas",
    "Taylor", "Moore", "Jackson", "Lee", "Perez", "White", "Harris", "Clark",
    "Lewis", "Walker", "Young", "King", "Wright", "Hill", "Green", "Baker",
]

INDUSTRIES = [
    "Financial Services", "Healthcare", "Retail & E-commerce", "Manufacturing",
    "Technology", "Media & Entertainment", "Education", "Logistics & Supply Chain",
    "Real Estate", "Professional Services", "Telecommunications", "Energy & Utilities",
    "Government & Public Sector", "Hospitality & Travel", "Non-Profit",
]

LOCATIONS = [
    "San Francisco, CA", "New York, NY", "Austin, TX", "Chicago, IL", "Seattle, WA",
    "Boston, MA", "Denver, CO", "Atlanta, GA", "Toronto, ON", "London, UK",
    "Dublin, IE", "Berlin, DE", "Amsterdam, NL", "Singapore, SG", "Sydney, AU",
    "Bangalore, IN", "Tokyo, JP", "Miami, FL", "Los Angeles, CA", "Remote / Distributed",
]

COMPANY_PREFIXES = [
    "Apex", "Nimbus", "Vertex", "Orbit", "Catalyst", "Beacon", "Summit", "Ledger",
    "Vector", "Meridian", "Fusion", "Quantum", "Pioneer", "Anchor", "Harbor",
    "Sterling", "Horizon", "Cascade", "Granite", "Cobalt", "Ironclad", "Bright",
    "Redwood", "Northstar", "Bluewave", "Crestline", "Silverline", "Falcon",
    "Lumen", "Atlas", "Zenith", "Pinnacle", "Keystone", "Momentum", "Trailhead",
]
COMPANY_SUFFIXES = [
    "Technologies", "Systems", "Solutions", "Analytics", "Labs", "Group",
    "Networks", "Dynamics", "Software", "Industries", "Partners", "Digital",
    "Health", "Robotics", "Logistics", "Capital", "Works", "Holdings",
]

JOB_TITLES = [
    "VP of Sales", "Chief Financial Officer", "Director of Operations",
    "Head of IT", "Chief Technology Officer", "VP of Marketing",
    "Director of Procurement", "Chief Executive Officer", "Head of Revenue Operations",
    "IT Manager", "VP of Engineering", "Director of Customer Success",
    "Chief Information Officer", "Procurement Manager", "VP of Product",
]

ACTIVITY_NOTES = {
    "Call": ["Discovery call re: current tooling gaps.", "Follow-up call on pricing questions.",
              "Check-in call, discussing timeline.", "Call to align on stakeholders."],
    "Email": ["Sent follow-up materials.", "Shared case study relevant to their industry.",
               "Emailed proposal draft for review.", "Sent meeting recap and next steps."],
    "Meeting": ["Stakeholder alignment meeting.", "Technical deep-dive with IT team.",
                 "Executive sponsor meeting.", "Kickoff meeting with buying committee."],
    "Demo": ["Product demo focused on reporting module.", "Live demo with technical evaluators.",
              "Custom demo tailored to their workflow.", "Follow-up demo addressing security questions."],
    "Proposal Sent": ["Sent formal proposal and pricing.", "Sent revised proposal after legal review."],
    "Contract Sent": ["Sent contract for signature.", "Sent redlined MSA for legal review."],
}


def _random_date(start: date, end: date) -> date:
    days = (end - start).days
    if days <= 0:
        return start
    return start + timedelta(days=random.randint(0, days))


def _weighted_choice(choices_with_weights):
    choices, weights = zip(*choices_with_weights)
    return random.choices(choices, weights=weights, k=1)[0]


def generate_sales_reps(n=28):
    """Generate a sales org: ~5-6 reps per region, hired at varying tenures."""
    reps = []
    used_names = set()
    for i in range(n):
        fn, ln = random.choice(FIRST_NAMES), random.choice(LAST_NAMES)
        tries = 0
        while (fn, ln) in used_names and tries < 200:
            fn, ln = random.choice(FIRST_NAMES), random.choice(LAST_NAMES)
            tries += 1
        used_names.add((fn, ln))
        region = REGIONS[i % len(REGIONS)]
        hire_date = _random_date(DATASET_START - relativedelta(years=2), TODAY - relativedelta(months=2))
        reps.append(SalesRep(first_name=fn, last_name=ln, region=region, hire_date=hire_date))
    return reps


def _assign_rep_skill(reps):
    # Each rep gets a hidden "skill" multiplier influencing win rate -- this
    # is what makes the leaderboard meaningful instead of uniform noise.
    return {rep_idx: random.uniform(0.55, 1.35) for rep_idx in range(len(reps))}


def generate_accounts(n=1050):
    accounts = []
    used_names = set()
    size_weights = [("SMB", 0.55), ("Mid-Market", 0.32), ("Enterprise", 0.13)]
    for i in range(n):
        base = f"{random.choice(COMPANY_PREFIXES)} {random.choice(COMPANY_SUFFIXES)}"
        name = base
        attempt = 1
        # COMPANY_PREFIXES x COMPANY_SUFFIXES gives ~630 unique combos, which
        # is fewer than the 1050+ accounts required by the spec, so once
        # combinations are exhausted we disambiguate with a numeric suffix
        # (e.g. "Apex Technologies II") rather than looping forever.
        while name in used_names:
            attempt += 1
            name = f"{base} {attempt}"
        used_names.add(name)
        accounts.append(
            Account(
                company_name=name,
                industry=random.choice(INDUSTRIES),
                company_size=_weighted_choice(size_weights),
                location=random.choice(LOCATIONS),
                created_date=_random_date(DATASET_START, TODAY - timedelta(days=1)),
            )
        )
    return accounts


def generate_contacts(accounts, min_per_account=1, max_per_account=3):
    """~2 contacts per account on average -> 2000+ for 1050 accounts."""
    contacts = []
    email_counts = {}
    for account in accounts:
        num_contacts = random.randint(min_per_account, max_per_account)
        domain = account.company_name.lower().replace(" ", "").replace("&", "and") + ".com"
        for _ in range(num_contacts):
            fn, ln = random.choice(FIRST_NAMES), random.choice(LAST_NAMES)
            key = f"{fn.lower()}.{ln.lower()}@{domain}"
            suffix = email_counts.get(key, 0)
            email_counts[key] = suffix + 1
            email = key if suffix == 0 else f"{fn.lower()}.{ln.lower()}{suffix}@{domain}"
            contacts.append(
                Contact(account=account, name=f"{fn} {ln}", job_title=random.choice(JOB_TITLES), email=email)
            )
    return contacts


DEAL_VALUE_BANDS = {
    # (mu, sigma) for a log-normal distribution, in dollars
    "SMB": (9.2, 0.45),          # centers ~ $10k
    "Mid-Market": (10.6, 0.5),   # centers ~ $40k
    "Enterprise": (12.2, 0.55),  # centers ~ $200k
}


def _sample_deal_value(company_size: str) -> float:
    mu, sigma = DEAL_VALUE_BANDS[company_size]
    value = random.lognormvariate(mu, sigma)
    return round(min(max(value, 1500), 1_500_000), 2)


def generate_opportunities(accounts, reps, rep_skill, n_target=1550):
    """
    Generate opportunities with realistic stage progression: created_date is
    sampled across the 3-year window (growth-weighted toward recent
    quarters), then stage/outcome is derived from elapsed time, company
    size, and rep skill -- so the funnel and win-rate analytics reflect
    real sales-motion patterns instead of uniform randomness.
    """
    opportunities = []
    opp_counter = 0

    quarter_starts = []
    d = DATASET_START
    while d < TODAY:
        quarter_starts.append(d)
        d = d + relativedelta(months=3)
    quarter_weights = [1.0 + 0.12 * i for i in range(len(quarter_starts))]

    for account in accounts:
        if account.company_size == "Enterprise":
            n_opps = random.choices([1, 2, 3], weights=[0.30, 0.35, 0.35])[0]
        elif account.company_size == "Mid-Market":
            n_opps = random.choices([1, 2], weights=[0.5, 0.5])[0]
        else:
            n_opps = random.choices([1, 2], weights=[0.7, 0.3])[0]

        for opp_n in range(n_opps):
            opp_counter += 1
            rep_idx = random.randrange(len(reps))
            rep = reps[rep_idx]
            skill = rep_skill[rep_idx]

            q_idx = _weighted_choice(list(zip(range(len(quarter_starts)), quarter_weights)))
            q_start = quarter_starts[q_idx]
            q_end = min(q_start + relativedelta(months=3), TODAY)
            lower = max(q_start, account.created_date)
            upper = max(q_end, account.created_date + timedelta(days=1))
            created = _random_date(lower, upper)

            days_elapsed = (TODAY - created).days
            deal_value = _sample_deal_value(account.company_size)

            cycle_days = {"SMB": 30, "Mid-Market": 60, "Enterprise": 110}[account.company_size]
            cycle_days = int(cycle_days * random.uniform(0.6, 1.6))
            progress = min(days_elapsed / cycle_days, 1.6)

            if progress < 0.15:
                stage, close_date = "Prospecting", None
            elif progress < 0.35:
                stage, close_date = random.choice(["Prospecting", "Qualification"]), None
            elif progress < 0.6:
                stage, close_date = random.choice(["Qualification", "Needs Analysis"]), None
            elif progress < 0.85:
                stage, close_date = random.choice(["Needs Analysis", "Proposal"]), None
            elif progress < 1.0:
                stage, close_date = random.choice(["Proposal", "Negotiation"]), None
            else:
                base_win_rate = {"SMB": 0.42, "Mid-Market": 0.34, "Enterprise": 0.27}[account.company_size]
                win_prob = min(max(base_win_rate * skill, 0.05), 0.85)
                if random.random() < 0.08:
                    # ~8% of "mature" deals stall indefinitely in open pipeline
                    stage, close_date = random.choice(OPEN_STAGES[2:]), None
                else:
                    won = random.random() < win_prob
                    stage = "Closed Won" if won else "Closed Lost"
                    raw_close = created + timedelta(days=min(int(cycle_days * random.uniform(0.8, 1.3)), max((TODAY - created).days, 1)))
                    close_date = min(raw_close, TODAY)

            opportunities.append(
                Opportunity(
                    account=account,
                    rep=rep,
                    opportunity_name=f"{account.company_name} - {'Renewal' if opp_n > 0 else 'New Business'} #{opp_counter}",
                    stage=stage,
                    deal_value=deal_value,
                    created_date=created,
                    close_date=close_date,
                )
            )

    return opportunities


STAGE_ACTIVITY_MIX = {
    "Prospecting": [("Call", 0.5), ("Email", 0.5)],
    "Qualification": [("Call", 0.4), ("Email", 0.35), ("Meeting", 0.25)],
    "Needs Analysis": [("Meeting", 0.35), ("Demo", 0.35), ("Call", 0.3)],
    "Proposal": [("Meeting", 0.25), ("Proposal Sent", 0.35), ("Email", 0.25), ("Call", 0.15)],
    "Negotiation": [("Call", 0.3), ("Email", 0.3), ("Contract Sent", 0.25), ("Meeting", 0.15)],
    "Closed Won": [("Call", 0.25), ("Email", 0.25), ("Meeting", 0.2), ("Contract Sent", 0.3)],
    "Closed Lost": [("Call", 0.4), ("Email", 0.4), ("Meeting", 0.2)],
}


def generate_activities(opportunities):
    activities = []
    for opp in opportunities:
        stage_rank = STAGE_CHOICES.index(opp.stage) if opp.stage in STAGE_CHOICES else 0
        base_count = 2 + stage_rank
        value_bonus = 1 if float(opp.deal_value) > 50_000 else 0
        n_activities = max(1, int(random.gauss(base_count + value_bonus, 1.5)))

        window_end = opp.close_date or TODAY
        window_start = opp.created_date
        mix = STAGE_ACTIVITY_MIX.get(opp.stage, [("Call", 0.5), ("Email", 0.5)])

        for _ in range(n_activities):
            activity_type = _weighted_choice(mix)
            activities.append(
                Activity(
                    opportunity=opp,
                    rep=opp.rep,
                    activity_type=activity_type,
                    activity_date=_random_date(window_start, max(window_end, window_start + timedelta(days=1))),
                    notes=random.choice(ACTIVITY_NOTES[activity_type]),
                )
            )
    return activities


def generate_full_dataset(n_accounts=1050, n_reps=28, opp_target=1550):
    """Orchestrates full dataset generation in dependency order."""
    random.seed(SEED)

    reps = generate_sales_reps(n_reps)
    rep_skill = _assign_rep_skill(reps)

    accounts = generate_accounts(n_accounts)
    contacts = generate_contacts(accounts)
    opportunities = generate_opportunities(accounts, reps, rep_skill, opp_target)
    activities = generate_activities(opportunities)

    return {
        "reps": reps,
        "accounts": accounts,
        "contacts": contacts,
        "opportunities": opportunities,
        "activities": activities,
    }
