* =====================================================================
* Adding_Batteries.gms
* Dispatch model (generators + ramping) extended with battery storage.
* All input data are read from csv files in the Inputs folder.
* =====================================================================
*
* ---------------------------- ASSUMPTIONS ----------------------------
*  A1. Each time step T is 1 hour, so 1 MW for 1 hour = 1 MWh.
*  A2. Battery data come from Inputs\Battery_in.csv:
*        cap           = energy capacity of the battery          [MWh]
*        power         = max charge / discharge per hour         [MW = MWh/h]
*        charg_eff     = one-way charging efficiency             [-]
*        discharge_eff = one-way discharging efficiency          [-]
*        inita_charge  = stored energy at the start of hour 1    [MWh]
*      (e.g. cap = 500 MWh, power = 50 MW -> 10 h to fill/empty;
*       round-trip efficiency = charg_eff*discharge_eff = 0.95*0.95 ~ 0.90)
*  A3. Charging losses: of Ch MWh taken from the grid, only charg_eff*Ch
*      is stored. Discharging losses: to deliver Dis MWh to the grid,
*      Dis/discharge_eff is removed from storage.
*  A4. No battery operating/degradation cost, no self-discharge and no
*      minimum state of charge.
*  A5. No binary variables prevent simultaneous charging and discharging.
*      Because both directions lose energy, doing both at once can only
*      waste energy, so the optimiser avoids it when prices are positive.
*      The model therefore stays a pure LP.
*  A6. Cyclic end-of-month condition: the battery starts at inita_charge
*      and must end the last hour (ord(T) = card(T)) at exactly
*      inita_charge, so no "free" energy is taken from storage.
*  A7. Generator, ramping, demand and load-factor equations are unchanged
*      apart from adding the battery to the demand balance.
*
* ---------------------------- EQUATIONS ------------------------------
*  Generators (unchanged):
*   Qcap        U(g,t) <= cap(g) * LF(t,g)
*   QVol_ramp_U Ramp_U(g,t) >= U(g,t) - U(g,t-1)            t > 1
*   QVol_ramp_D Ramp_D(g,t) >= U(g,t-1) - U(g,t)            t > 1
*   QRamp_U     Ramp_U(g,t) <= ramp_L(g)*cap(g)              t > 1
*   QRamp_D     Ramp_D(g,t) <= ramp_L(g)*cap(g)              t > 1
*   QPlant      PlantCost(g,t) = vom*U + cost*U/eff + ramp_cost*(Ramp_U+Ramp_D)
*   QCost       Cost(t) = sum(g, PlantCost(g,t))
*   QTOTCost    TOTCost = sum(t, Cost(t))
*
*  Battery (new):
*   QSOC_first  SOC(b,t) = inita_charge(b) + charg_eff(b)*Ch(b,t)
*                          - Dis(b,t)/discharge_eff(b)            t = 1
*   QSOC        SOC(b,t) = SOC(b,t-1) + charg_eff(b)*Ch(b,t)
*                          - Dis(b,t)/discharge_eff(b)            t > 1
*   QSOC_end    SOC(b,t) = inita_charge(b)                  t = card(T)
*   QSOC_cap    SOC(b,t) <= cap(b)
*   QCh_cap     Ch(b,t)  <= power(b)
*   QDis_cap    Dis(b,t) <= power(b)
*
*  Demand balance (modified):
*   QDemand     sum(g, U(g,t)) + sum(b, Dis(b,t)) - sum(b, Ch(b,t)) = d(t)
*
*  Objective: minimise TOTCost
* =====================================================================
$offeolcom
$eolcom #
option lp = mosek;

SETS
            T       List of all time Hours
* this means all hours from 1 to 744
                    /1*744/
            gen     generators
                    /Solar,Coal,Gas,Wind/
            f       diffrent fields
                    /cost,cap,eff,vom,ramp_L,ramp_cost/
            b       batteries
                    /bat_1/
            bf      battery fields
                    /cap,power,charg_eff,discharge_eff,inita_charge/
            outfield Output columns
                    /DemandMarginal,Demand,Solar,Coal,Gas,Wind,Bat_Charge,Bat_Discharge,Bat_SOC/; #cost($/MWhTh),Cap (MW),eff (MWh/MWhTh),vom($/MWh)


PARAMETERS
data(gen,f) Input data for cost, capacity, efficiency, and variable O&M for each generator
bat_data(b,bf) Input data for each battery
PRD_DATA(T) Input data for production quantity
d(T) Input data for demand for each hour
Load_factor(T,gen) Input data for load factor for each hour
Ramp(gen,T)   Ramp for each generator and hour
ExcelResults(T,outfield) Values exported to Excel;



$call csv2gdx Inputs\Renewable_intermit.csv id=data_in index =1 values =2..7 useHeader=y output=Inputs\Renewable_intermit.gdx

$gdxin Inputs\Renewable_intermit.gdx
$load data = data_in
$gdxin

* Battery input data
$call csv2gdx Inputs\Battery_in.csv id=bat_data index=1 values=2..6 useHeader=y output=Inputs\Battery_in.gdx
$gdxin Inputs\Battery_in.gdx
$load bat_data
$gdxin

* Optional overrides passed from the dashboard (defaults keep the original behaviour)
$if not set outdir $set outdir Results
$if set solarCap data('Solar','cap') = %solarCap%;
$if set coalCap data('Coal','cap') = %coalCap%;
$if set gasCap data('Gas','cap') = %gasCap%;
$if set windCap data('Wind','cap') = %windCap%;
$if set batCap bat_data(b,'cap') = %batCap%;
$if set batPower bat_data(b,'power') = %batPower%;
$if set batChEff bat_data(b,'charg_eff') = %batChEff%;
$if set batDisEff bat_data(b,'discharge_eff') = %batDisEff%;


* Assigning cost for each generator based on the excel input
$call csv2gdx Inputs\demand(in).csv id=d index =1 values =2 useHeader=y output=Inputs\demand(in).gdx
$gdxin Inputs\demand(in).gdx
$load d
$gdxin

$call csv2gdx Inputs\normalisedloads.csv id=Load_factor index =1 values =2..5 useHeader=y output=Inputs\normalisedloads.gdx
$gdxin Inputs\normalisedloads.gdx
$load Load_factor
$gdxin

PRD_DATA(T) = d(T); #MWh
Ramp(gen,T) = data(gen,'ramp_L')*data(gen,'cap'); #MWh

DISPLAY bat_data;

VARIABLES
TOTCost     Total cost of emissions for all hours
Cost(T)     Total cost for each hour
U(gen,T)   Utilization of each generator for each hour
PlantCost(gen,T)   Cost for each generator and hour
Ramp_U(gen,T)   Ramp utilization for each generator and hour
Ramp_D(gen,T)   Ramp down utilization for each generator and hour
Ch(b,T)     Energy charged into battery from the grid in hour T (MWh)
Dis(b,T)    Energy discharged from battery to the grid in hour T (MWh)
SOC(b,T)    Stored energy (state of charge) at end of hour T (MWh)
;

POSITIVE VARIABLES U, PlantCost, Cost, Ramp_U, Ramp_D, Ch, Dis, SOC;


EQUATIONS
* The equation definition block:
Qcap(gen,T)   Equation for utilization of each generator
QDemand(T)   Equation for demand satisfaction (incl. battery)
QCost(T)   Equation for total cost for each hour
QTOTCost   Equation for total cost for all hours
QPlant(gen,T)   Equation for cost of each generator and hour
QVol_ramp_U(gen,T)   Equation for ramp volume for each generator and hour
QVol_ramp_D(gen,T)   Equation for ramp down volume for each generator and hour
QRamp_U(gen,T)   Equation for ramp up for each generator and hour
QRamp_D(gen,T)   Equation for ramp down for each generator and hour
QSOC_first(b,T)  Battery energy balance in the first hour
QSOC(b,T)        Battery energy balance for hours after the first
QSOC_end(b,T)    Cyclic condition - last hour SOC equals initial charge
QSOC_cap(b,T)    Battery energy capacity limit
QCh_cap(b,T)     Battery charging power limit
QDis_cap(b,T)    Battery discharging power limit
;

*this means that the equation only applies for time periods greater than 1 so that ramping up from 0 isnt considered
QVol_ramp_U(gen,T)$(ord(T)>1).. Ramp_U(gen,T) =g= U(gen,T) - U(gen,T-1); #MWh
QVol_ramp_D(gen,T)$(ord(T)>1).. Ramp_D(gen,T) =g= U(gen,T-1) - U(gen,T); #MWh

QRamp_U(gen,T)$(ord(T)>1).. Ramp_U(gen,T) =l= Ramp(gen,T); #MWh
QRamp_D(gen,T)$(ord(T)>1).. Ramp_D(gen,T) =l= Ramp(gen,T); #MWh

Qcap(gen,T)..	U(gen,T) =l=data(gen,'cap')*Load_factor(T,gen); #MWh

* Demand balance: generation + battery discharge - battery charge = demand
QDemand(T)..	 sum(gen, U(gen,T)) + sum(b, Dis(b,T)) - sum(b, Ch(b,T)) =E= PRD_DATA(T); #MWh

* ---------------- Battery equations ----------------
* Hour 1: starts from the initial charge given in the csv
QSOC_first(b,T)$(ord(T)=1)..  SOC(b,T) =E= bat_data(b,'inita_charge')
                                         + bat_data(b,'charg_eff')*Ch(b,T)
                                         - Dis(b,T)/bat_data(b,'discharge_eff'); #MWh
* Hours 2..card(T): carry over stored energy from previous hour
QSOC(b,T)$(ord(T)>1)..        SOC(b,T) =E= SOC(b,T-1)
                                         + bat_data(b,'charg_eff')*Ch(b,T)
                                         - Dis(b,T)/bat_data(b,'discharge_eff'); #MWh
* Cyclic end-of-month condition: last hour returns to the initial charge
QSOC_end(b,T)$(ord(T)=card(T))..  SOC(b,T) =E= bat_data(b,'inita_charge'); #MWh

QSOC_cap(b,T)..  SOC(b,T) =l= bat_data(b,'cap');   #MWh
QCh_cap(b,T)..   Ch(b,T)  =l= bat_data(b,'power'); #MWh per hour
QDis_cap(b,T)..  Dis(b,T) =l= bat_data(b,'power'); #MWh per hour

* Equations for calculating the production cost for each plant based on utilization and cost parameters
QPlant(gen,T)..	PlantCost(gen,T) =E= data(gen,'vom')*U(gen,T) + data(gen,'cost')*U(gen,T)/data(gen,'eff') + $ord(T)>1data(gen,'ramp_cost')*(Ramp_U(gen,T) + Ramp_D(gen,T)); # dollars

* Equations for calculating the total cost for each hour and the total cost for all hours (battery has no cost - A4)
QCost(T)..	Cost(T) =E= sum(gen, PlantCost(gen,T));
QTOTCost..	TOTCost =E= SUM(T, Cost(T));

MODEL CLIMATE /ALL/;
SOLVE CLIMATE USING lp MINIMIZING TOTCost;

DISPLAY QDemand.M, TOTCost.L, U.L, Ch.L, Dis.L, SOC.L;

ExcelResults(T,'DemandMarginal') = QDemand.M(T);
ExcelResults(T,'Demand') = d(T); #MWh
ExcelResults(T,'Solar') = U.L('Solar',T);
ExcelResults(T,'Coal') = U.L('Coal',T);
ExcelResults(T,'Gas') = U.L('Gas',T);
ExcelResults(T,'Wind') = U.L('Wind',T);
ExcelResults(T,'Bat_Charge') = sum(b, Ch.L(b,T));
ExcelResults(T,'Bat_Discharge') = sum(b, Dis.L(b,T));
ExcelResults(T,'Bat_SOC') = sum(b, SOC.L(b,T));

execute_unload '%outdir%\Batteries.gdx', ExcelResults;

$if not set noxlsx execute 'gdxxrw %outdir%\Batteries.gdx output=%outdir%\Batteries.xlsx squeeze=n par=ExcelResults rng=Hourly!A1';
