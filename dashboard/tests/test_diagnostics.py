import pandas as pd
import pytest

from dashboard import config
from dashboard.data import diagnostics as D, loader, lst_parser

LST = """\fGAMS 25.1.3  r4e34d435fbd Released Oct 30, 2018 WEX-WEI      10/15/26 14:21:23 Page 9
BLOCKS OF EQUATIONS           5     SINGLE EQUATIONS        5,953
BLOCKS OF VARIABLES           4     SINGLE VARIABLES        5,209
NON ZERO ELEMENTS        12,649
GENERATION TIME      =        0.016 SECONDS      6 MB
EXECUTION TIME       =        0.016 SECONDS      6 MB
     MODEL   CLIMATE             OBJECTIVE  TOTCost
     TYPE    LP                  DIRECTION  MINIMIZE
     SOLVER  MOSEK               FROM LINE  75
**** SOLVER STATUS     1 Normal Completion
**** MODEL STATUS      1 Optimal
**** OBJECTIVE VALUE          3100391.5775
 RESOURCE USAGE, LIMIT          0.000      1000.000
 ITERATION COUNT, LIMIT         9    2000000000

---- EQU Qcap  Equation for utilization of each generator

                 LOWER          LEVEL          UPPER         MARGINAL

Solar.1          -INF          435.4572       500.0000          .
Solar.2          -INF          500.0000       500.0000       -20.5000
\fGAMS 25.1.3  r4e34d435fbd Released Oct 30, 2018 WEX-WEI      10/15/26 14:21:23 Page 10
     EQU Qcap  Equation for utilization of each generator

                 LOWER          LEVEL          UPPER         MARGINAL

Coal .1          -INF             .           100.0000          EPS
Coal .2          -INF          100.0000       100.0000       -20.1000

---- EQU QDemand  Equation for demand satisfaction
Solar.3          -INF          1.0000       500.0000       -99.0000
                                0 INFEASIBLE
EXECUTION TIME       =        2.391 SECONDS      4 MB
"""


@pytest.fixture
def params():
    return pd.DataFrame({"cost": [0, 7.8, 19.8], "cap": [500, 100, 600],
                         "eff": [1, 0.4, 0.5], "vom": [1, 2, 2]},
                        index=pd.Index(["Solar", "Coal", "Gas"], name="gen"))


def test_parse_summary():
    s = lst_parser.parse_summary(LST)
    assert s["solver"] == "MOSEK" and s["model_status"] == "Optimal" and s["model_status_code"] == 1
    assert s["objective"] == pytest.approx(3100391.5775)
    assert s["iterations"] == 9 and s["single_equations"] == 5953 and s["non_zeros"] == 12649
    assert s["infeasible"] == 0 and s["execution_time"] == pytest.approx(2.391)
    assert s["gams_version"] == "25.1.3" and s["solve_date"] == "10/15/26 14:21:23"


def test_parse_marginals_page_breaks_and_dots():
    q = lst_parser.parse_equ_marginals(LST, "Qcap")
    assert len(q) == 4  # stops at next ---- EQU
    assert list(q["gen"]) == ["Solar", "Solar", "Coal", "Coal"]
    assert q["marginal"].tolist() == [0.0, -20.5, 0.0, -20.1]
    assert q.loc[2, "level"] == 0.0


def test_gen_params_from_long(params):
    long = pd.DataFrame([(g, f, params.loc[g, f]) for g in params.index for f in params.columns
                         if not (g == "Solar" and f == "cost")], columns=["*", "*", "Value"])
    out = loader.gen_params_from_long(long)
    assert out.loc["Solar", "cost"] == 0.0 and out.loc["Gas", "cap"] == 600


def test_srmc_and_merit_order(params):
    assert D.srmc(params).round(2).to_dict() == {"Solar": 1.0, "Coal": 21.5, "Gas": 41.6}
    m = D.merit_order(params)
    assert list(m["gen"]) == ["Solar", "Coal", "Gas"] and list(m["cum_end"]) == [500, 600, 1200]


def test_objective_check():
    df = pd.DataFrame({"total_cost": [100.0, 200.0]})
    assert D.objective_check(df, 300.0)["ok"] is True
    bad = D.objective_check(df, 400.0)
    assert bad["ok"] is False and bad["diff"] == -100.0
    assert D.objective_check(df, None)["ok"] is None


def test_price_setter_and_capacity(params):
    w = pd.DataFrame({"T": [1, 2, 3, 4], "price": [1.0, 21.5, 41.6, 30.0],
                      "demand": [400, 550, 800, 600], "Solar": [400, 500, 500, 500],
                      "Coal": [0, 50, 100, 100], "Gas": [0, 0, 200, 0]})
    d = D.price_setter(w, params).set_index("setter")["hours"].to_dict()
    assert d == {"Solar": 1, "Coal": 1, "Gas": 1, D.OTHER: 1}
    summ, per = D.capacity_checks(w, params)
    assert summ["peak_demand"] == 800 and summ["adequate"]
    assert per.set_index("gen")["hours_at_cap"].to_dict() == {"Solar": 3, "Coal": 2, "Gas": 0}


def test_capacity_value(params):
    q = lst_parser.parse_equ_marginals(LST, "Qcap")
    w = pd.DataFrame({"T": [2], "datetime": [pd.Timestamp("2024-01-01 01:00")]})
    hourly, summ = D.capacity_value(q, w, ["Solar", "Coal"])
    assert summ.set_index("gen")["total_value_per_mw"].to_dict() == {"Solar": 20.5, "Coal": 20.1}


def test_diagnostics_layout_has_all_sections():
    from dashboard.pages import diagnostics
    ids = str(diagnostics.layout())
    for k, _ in diagnostics.SECTIONS:
        assert "d-" + k in ids
    assert len(diagnostics.SECTIONS) == 10
