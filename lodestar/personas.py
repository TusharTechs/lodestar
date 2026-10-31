"""Buyer personas scored on go-to-market factors (team judgement, with the evidence for each score).

Factors suggested by a hackathon mentor: urgency (whose head is most on fire), value / ability to pay,
accessibility (fastest, least friction). Data flywheel added: who can feed the Demand Bureau with meters.
"""

FACTORS = [("urgency", "Urgency: whose head is most on fire"), ("value", "Value / ability to pay"),
           ("access", "Accessibility: fastest, least friction"), ("data", "Feeds the Demand Bureau (data flywheel)")]

PERSONAS = [
    {"key": "developer", "group": "Mini-grid developers",
     "person": "Head of project development at a Nigerian developer bidding for RBF-funded sites",
     "job": "Pick and size 10-30 sites a year; win the grant; raise the rest as equity or debt",
     "scores": {"urgency": 5, "value": 3, "access": 4, "data": 5},
     "why": {"urgency": "Sizes every site before any customer exists and carries the over/undersizing risk; must defend a demand number to grant programmes and lenders.",
             "value": "Cash-constrained (AMDA: 68% of developer funding is equity, 20% debt), but $300 is 0.05% of a ~$585k site.",
             "access": "Many small firms, reachable through AMDA and industry networks; the CEO or project head decides; free tier is self-serve.",
             "data": "Owns the meters: each customer can contribute site-months to the Bureau."},
     "role": "primary"},
    {"key": "rbf", "group": "Results-based financing programmes",
     "person": "Programme manager of an RBF window (e.g. Nigeria's DARES, 1,000+ planned mini-grids)",
     "job": "Choose which communities get mini-grids and size grants across hundreds of sites",
     "scores": {"urgency": 4, "value": 5, "access": 2, "data": 5},
     "why": {"urgency": "DARES explicitly uses data-driven planning to identify communities (AMDA 2024); grants per connection ($350-600 under NEP) must be allocated well.",
             "value": "Largest budget; one portfolio contract covers hundreds of sites.",
             "access": "Procurement and tenders; needs a track record before buying.",
             "data": "Already verifies metered connections; one clause in grant agreements could seed the Bureau."},
     "role": "secondary"},
    {"key": "lender", "group": "Lenders and DFIs",
     "person": "Investment officer at a mini-grid debt fund or DFI",
     "job": "Decide how much debt a site or portfolio can carry",
     "scores": {"urgency": 3, "value": 4, "access": 2, "data": 2},
     "why": {"urgency": "AMDA flags 'significant demand risk' in rural mini-grids, but lenders can wait or require grants instead.",
             "value": "Due-diligence budgets; avoiding one default pays for many reports; P90 is their native language.",
             "access": "Few institutions, long credit processes; will want the forecast ledger's track record first.",
             "data": "See repayment data, not meter data."},
     "role": "later"},
    {"key": "community", "group": "Households and businesses",
     "person": "A household or shop owner in an unelectrified village",
     "job": "Get reliable power at a price they can afford",
     "scores": {"urgency": 5, "value": 1, "access": 1, "data": 1},
     "why": {"urgency": "They live with the outcome: oversizing raises tariffs, undersizing means brownouts.",
             "value": "Should never pay for the forecast; they benefit through right-sized systems and tariffs.",
             "access": "Reached through developers and USSD/SMS, not as buyers.",
             "data": "Their consumption is what the meters record, aggregated by operators."},
     "role": "beneficiary"},
]

for p in PERSONAS:
    p["buyer_score"] = p["scores"]["urgency"] + p["scores"]["value"] + p["scores"]["access"]

STRATEGY = ("Start with developers bidding into RBF programmes: their head is most on fire, they decide fast, and their meters feed "
            "the Demand Bureau. Every report they submit with a grant application shows the programme the method; that is the "
            "route to the RBF portfolio contract (largest value). Lenders follow once the public ledger has 12-18 months of "
            "scored forecasts.")
