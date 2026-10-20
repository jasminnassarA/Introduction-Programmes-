* =====================================================================
* Nodal_SC.gms
* Nodal pricing scenario: least-cost dispatch under transmission
* constraints (DC power flow via shift factors / PTDF).
* All input data are read from csv files in Inputs\Nodes_in.
* =====================================================================
*
* ---------------------------- ASSUMPTIONS ----------------------------
*  A1. Each time step T is 1 hour (168 hours = 1 week), 1 MW for 1 h = 1 MWh.
*  A2. Generator data (Inputs\Nodes_in\generators(in).csv):
*        MC   = marginal cost                                  ($ per MWh)
*        CAP  = maximum output, constant in every hour         (MW)
*        NODE = node the generator is connected to
*      No ramping, minimum output, efficiency or O&M terms.
*  A3. DC power flow with shift factors: the flow on line l is
*        Flow(l,t) = sum(n, PTDF(l,n) * NetInj(n,t))
*      NetInj = generation + unserved energy - demand at node n.
*      The PTDF column of the reference (slack) bus is zero.
*  A4. Flows are tracked on ALL lines. Only lines with a finite rating
*      get +/- rating limits. Lines rated "inf" are unlimited.
*  A5. One system-wide energy balance per hour (lossless network).
*  A6. Unserved energy LS(n,t) is allowed at demand nodes at VOLL
*      (10 000 $/MWh), which keeps the LP always feasible.
*  A7. Nodal price (LMP) = system energy price + congestion component:
*        LMP(n,t) = QBal.M(t) + sum(l, PTDF(l,n)*(QFmax.M(l,t)+QFmin.M(l,t)))
*      (QFmax.M <= 0, QFmin.M >= 0 in GAMS sign conventions.)
*
* ---------------------------- EQUATIONS ------------------------------
*   QObj     TOTCost = sum(g,t, MC(g)*P(g,t)) + VOLL*sum(n,t, LS(n,t))
*   QBal     sum(g, P(g,t)) + sum(n, LS(n,t)) = sum(n, dem(t,n))
*   QFlow    Flow(l,t) = sum(n, PTDF(l,n)*NetInj(n,t))       all lines
*   QFmax    Flow(l,t) <=  rating(l)                         finite only
*   QFmin    Flow(l,t) >= -rating(l)                         finite only
*   Bounds   0 <= P(g,t) <= CAP(g),  LS(n,t) >= 0
* =====================================================================
$offeolcom
$eolcom #
option lp = mosek, limrow = 0, limcol = 0, solprint = off;

$if not set outdir $set outdir Results
$set indir Inputs\Nodes_in

SETS
    T     hours /1*168/
    l     transmission lines
    n     network nodes
    g     generators
    f     generator fields
    dn(n) nodes with demand
    gn(g,n) generator-to-node map
;

PARAMETERS
    ptdf(l,n)     shift factor of node n on line l (MW per MW)
    rating(l)     thermal rating of line l (MW)
    dem(T,n)      hourly demand per node (MWh)
    gdata(g,n,f)  generator data indexed by its node
    MC(g)         marginal cost ($ per MWh)
    CAP(g)        capacity (MW)
    VOLL          value of lost load in $ per MWh /10000/
;

* ---------------- Shift factor matrix (defines lines and nodes) ----------------
$call csv2gdx "%indir%\shiftfactormatrix(in).csv" id=ptdf index=1 values=2..lastCol useHeader=y output="%indir%\shiftfactormatrix(in).gdx"
$gdxin "%indir%\shiftfactormatrix(in).gdx"
$load l=Dim1 n=Dim2 ptdf
$gdxin

* ---------------- Line ratings ("inf" -> +INF) ----------------
$call csv2gdx "%indir%\lineratings(in).csv" id=rating index=1 values=2 useHeader=y output="%indir%\lineratings(in).gdx"
$gdxin "%indir%\lineratings(in).gdx"
$load rating
$gdxin

* ---------------- Hourly demand by node ----------------
* The reference (slack) bus has an all-zero PTDF column, so csv2gdx drops it from
* the shift factor gdx. Merge the demand nodes (and generator nodes below) into n
* with $loadM so no demand is filtered out by the domain check.
$call csv2gdx "%indir%\hourlydemandbynode(in).csv" id=dem index=1 values=2..lastCol useHeader=y output="%indir%\hourlydemandbynode(in).gdx"
$gdxin "%indir%\hourlydemandbynode(in).gdx"
$loadM n=Dim2
$load dem
$gdxin
PARAMETER demRaw(*,*) demand without domain checking (for the completeness check);
$gdxin "%indir%\hourlydemandbynode(in).gdx"
$load demRaw=dem
$gdxin

* ---------------- Generators (NODE column used as 2nd index) ----------------
$call csv2gdx "%indir%\generators(in).csv" id=gdata index=1,4 values=2..3 useHeader=y output="%indir%\generators(in).gdx"
$gdxin "%indir%\generators(in).gdx"
$loadM n=Dim2
$load g=Dim1 f=Dim3 gdata
$gdxin

SCALAR demCheck total demand loaded minus csv total (must be 0);
ALIAS (*, u1, u2);
demCheck = sum((T,n), dem(T,n)) - sum((u1,u2)$demRaw(u1,u2), demRaw(u1,u2));
ABORT$(abs(demCheck) > 1e-6) "Demand was dropped while loading", demCheck;
gn(g,n)$gdata(g,n,'CAP') = yes;
MC(g)    = sum(gn(g,n), gdata(g,n,'MC'));
CAP(g)   = sum(gn(g,n), gdata(g,n,'CAP'));
dn(n)    = yes$sum(T, dem(T,n));

SCALAR nInfLines number of unlimited lines, nLimLines number of rated lines;
nInfLines = sum(l$(rating(l) = inf), 1);
nLimLines = sum(l$(rating(l) < inf), 1);
DISPLAY nInfLines, nLimLines, MC, CAP, gn;
ABORT$(nInfLines + nLimLines <> card(l)) "Line ratings missing for some lines", rating;

VARIABLES
    TOTCost       total dispatch cost                         ($)
    Flow(l,T)     flow on line l                              (MW)
;
POSITIVE VARIABLES
    P(g,T)        generation                                  (MWh)
    LS(n,T)       unserved energy                             (MWh)
;
P.up(g,T) = CAP(g);
LS.fx(n,T)$(not dn(n)) = 0;

EQUATIONS
    QObj          objective
    QBal(T)       system energy balance
    QFlow(l,T)    shift factor flow definition (all lines)
    QFmax(l,T)    line limit positive direction (finite ratings)
    QFmin(l,T)    line limit negative direction (finite ratings)
;

QObj..  TOTCost =E= sum((g,T), MC(g)*P(g,T)) + VOLL*sum((dn,T), LS(dn,T)); # $

QBal(T).. sum(g, P(g,T)) + sum(dn, LS(dn,T)) =E= sum(dn, dem(T,dn)); # MWh

QFlow(l,T).. Flow(l,T) =E= sum(n, ptdf(l,n)*( sum(gn(g,n), P(g,T))
                                             + LS(n,T)$dn(n)
                                             - dem(T,n) )); # MW

QFmax(l,T)$(rating(l) < inf)..  Flow(l,T) =L=  rating(l);
QFmin(l,T)$(rating(l) < inf)..  Flow(l,T) =G= -rating(l);

MODEL NODAL /ALL/;
SOLVE NODAL USING lp MINIMIZING TOTCost;

* ---------------- Post-processing ----------------
SETS
    pn(n)  nodes reported in LMP sheet
    dcol   dispatch columns /SystemPrice, TotalDemand, Unserved/
    fcol   flow columns /Flow, Rating, CongestionPrice/
;
pn(n) = dn(n) + sum(g, gn(g,n));

PARAMETERS
    LMP(T,n)            nodal price                           ($ per MWh)
    CongPrice(l,T)      shadow price of line limit             ($ per MWh)
    Dispatch(T,*)       hourly dispatch report
    LMPrep(T,n)         LMP at demand and generator nodes
    FlowRep(l,T,fcol)   line flow report
    LMPcheck(T)         max - min LMP over reported nodes
;
CongPrice(l,T) = (QFmax.M(l,T) + QFmin.M(l,T))$(rating(l) < inf);
LMP(T,n) = QBal.M(T) + sum(l, ptdf(l,n)*CongPrice(l,T));
LMPrep(T,pn) = LMP(T,pn) + eps;
LMPcheck(T) = smax(pn, LMP(T,pn)) - smin(pn, LMP(T,pn));

Dispatch(T,g)             = P.L(g,T) + eps;
Dispatch(T,'SystemPrice') = QBal.M(T) + eps;
Dispatch(T,'TotalDemand') = sum(dn, dem(T,dn));
Dispatch(T,'Unserved')    = sum(dn, LS.L(dn,T)) + eps;

FlowRep(l,T,'Flow')            = Flow.L(l,T) + eps;
FlowRep(l,T,'Rating')$(rating(l) < inf) = rating(l);
FlowRep(l,T,'CongestionPrice') = abs(CongPrice(l,T)) + eps;

SCALAR totUnserved total unserved energy (MWh), nCongested number of congested line-hours;
totUnserved = sum((dn,T), LS.L(dn,T));
nCongested  = sum((l,T)$(CongPrice(l,T) <> 0), 1);
* Sanity check: a generator strictly between 0 and CAP is marginal,
* so the LMP at its node must equal its MC.
PARAMETER MargCheck(g,T) LMP minus MC for marginal generators;
MargCheck(g,T)$(P.L(g,T) > 1e-4 and P.L(g,T) < CAP(g) - 1e-4)
    = sum(gn(g,n), LMP(T,n)) - MC(g) + eps;
SCALAR maxMargErr largest abs LMP-MC gap at marginal units;
maxMargErr = smax((g,T), abs(MargCheck(g,T)));
DISPLAY TOTCost.L, totUnserved, nCongested, maxMargErr, LMPcheck;

execute_unload '%outdir%\Nodal_SC.gdx', Dispatch, LMP, LMPrep, FlowRep, CongPrice, P, LS, Flow, TOTCost, ptdf, rating, dem;

$if not set noxlsx execute 'gdxxrw %outdir%\Nodal_SC.gdx output=%outdir%\Nodal_SC.xlsx squeeze=n par=Dispatch rng=Dispatch!A1 par=LMPrep rng=LMP!A1 par=FlowRep rng=Flows!A1 rdim=1 cdim=2';
