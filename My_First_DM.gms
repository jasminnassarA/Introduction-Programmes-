* My attempt at trying to use csv files for simplicity instead of manually entering data
$offeolcom
$eolcom #
option lp = mosek;

SETS
            T       List of all time Hours
* this means all hours from 1 to 744
                    /1*744/
            gen     generators 
                    /Solar,Coal,Gas/
            f       diffrent fields 
                    /cost,cap,eff,vom/; #cost($/MWhTh),Cap (MW),eff (MWh/MWhTh),vom($/MWh)


PARAMETERS
data(gen,f)   Input data for cost, capacity, efficiency, and variable O&M for each generator
PRD_DATA(T)   Input data for production quantity
d(T)   Demand for each hour;

*Note to self = i can assign the values in data(gen,f) to there own Peramerter/Scalar if i think i will get confusing
* Question -> is this better as it is more consice or should i assign each value individually for clarity? 


$call csv2gdx Inputs\base_case.csv id=data_in index =1 values =2..5 useHeader=y output=Inputs\base_case.gdx

$gdxin Inputs\base_case.gdx
$load data = data_in
$gdxin


* Assigning cost for each generator based on the excel input
$call csv2gdx Inputs\demand(in).csv id=d index =1 values =2 useHeader=y output=Inputs\demand(in).gdx
$gdxin Inputs\demand(in).gdx
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
QUS(T)..	U_solar(T) =l=data('Solar','cap'); #MWh
QCOAL(T)..	U_Coal(T) =l=data('Coal','cap'); #MWh
QGAS(T)..	U_Gas(T) =l=data('Gas','cap'); #MWh 
QDemand(T)..	PRD_DATA(T) =E= U_solar(T) + U_Coal(T) + U_Gas(T) ; #MWh 

* Equations for calculating the production cost for each plant based on utilization and cost parameters
QPlant1(T)..	Plant1(T) =E= data('Solar','vom')*U_solar(T)+ data('Solar','cost')*U_solar(T)/data('Solar','eff'); 
QPlant2(T)..	Plant2(T) =E= data('Coal','vom')*U_Coal(T) + data('Coal','cost')*U_Coal(T)/data('Coal','eff'); # dollars
QPlant3(T)..	Plant3(T) =E= data('Gas','vom')*U_Gas(T) + data('Gas','cost')*U_Gas(T)/data('Gas','eff'); # Dollars

* Equations for calculating the total cost for each hour and the total cost for all hours
QCost(T)..	Cost(T) =E= Plant1(T) + Plant2(T) + Plant3(T);
QTOTCost..	TOTCost =E= SUM(T, Cost(T));

MODEL CLIMATE /ALL/;
SOLVE CLIMATE USING lp MINIMIZING TOTCost;

DISPLAY QDemand.M, TOTCost.L;

