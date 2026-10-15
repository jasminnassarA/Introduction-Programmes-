$offeolcom
$eolcom #
option lp = mosek;

SETS
            T       List of all time Hours
* this means all hours from 1 to 744
                    /1*744/;    

PARAMETERS
C_coal(T)     Cost of coal per unit for each hour
C_gas(T)      Cost of gas per unit for each hour
C_solar(T)    Cost of solar per unit for each hour
PRD_DATA(T)   Input data for production quantity
MAX_Marg(T)   Maximum marginal cost for each hour
d(T)   Demand for each hour;

C_coal(T) = 7.8; # $/MWhTh
C_gas(T) = 19.8; # $/MWhTh

$call csv2gdx demand(in).csv id=d index =1 values =2 useHeader=y output=demand(in).gdx
$gdxin demand(in).gdx
$load d
$gdxin

PRD_DATA(T) = d(T); #MWh

VARIABLES
TOTCost     Total cost of emissions for all hours
Cost(T)     Total cost for each hour
U_solar(T)     Utilization of solar energy for each hour
U_Coal(T)     Utilization of coal energy for each hour
U_Gas(T)     Utilization of gas energy for each hour
Plant1(T)   Production for Plant 1 for each hour
Plant2(T)   Production for Plant 2 for each hour
Plant3(T)   Production for Plant 3 for each hour
;

POSITIVE VARIABLES U_solar,U_Coal,U_Gas, Plant1, Plant2, Plant3, Cost;



EQUATIONS
* The equation definition block:
QUS(T)     Equation for Solar Utililzation 
QCOAL(T)   Equation for coal utilization
QGAS(T)    Equation for gas utilization
QDemand(T)   Equation for demand satisfaction
QCost(T)   Equation for total cost for each hour
QTOTCost   Equation for total cost for all hours
QPlant1(T)   Equation for Plant 1 production
QPlant2(T)   Equation for Plant 2 production
QPlant3(T)   Equation for Plant 3 production
;

* 0.4 (plant 2)= effieceny for coal and 0.5 (plant 3)= efficaieny for gas 
QUS(T)..	U_solar(T) =l= 500; #MWh
QCOAL(T)..	U_Coal(T) =l= 100; #MWh
QGAS(T)..	U_Gas(T) =l= 600; #MWh
*Demand 
QDemand(T)..	PRD_DATA(T) =E= U_solar(T) + U_Coal(T) + U_Gas(T) ; #MWh 
* cost of each gen
QPlant1(T)..	Plant1(T) =E= 1*U_solar(T); 
QPlant2(T)..	Plant2(T) =E= 2*U_Coal(T) + C_coal(T)*U_Coal(T)/0.4; # dollars
QPlant3(T)..	Plant3(T) =E= 2*U_Gas(T) + C_gas(T)*U_Gas(T)/0.5; # Dollars
*Calc cost tot
QCost(T)..	Cost(T) =E= Plant1(T) + Plant2(T) + Plant3(T);
QTOTCost..	TOTCost =E= SUM(T, Cost(T));
MODEL CLIMATE /ALL/;
SOLVE CLIMATE USING lp MINIMIZING TOTCost;

DISPLAY QDemand.M, TOTCost.L;
