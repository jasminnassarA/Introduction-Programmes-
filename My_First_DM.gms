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
                    /cost,cap,eff,vom/
            outfield Output columns
                    /DemandMarginal,Solar,Coal,Gas/; #cost($/MWhTh),Cap (MW),eff (MWh/MWhTh),vom($/MWh)


PARAMETERS
data(gen,f) "Input data for cost, capacity, efficiency, and variable O&M for each generator"
PRD_DATA(T) "Input data for production quantity"
d(T) "Demand for each hour"
ExcelResults(T,outfield) "Values exported to Excel";

*Note to self = i can assign the values in data(gen,f) to there own Peramerter/Scalar if i think i will get confusing
* Question -> is this better as it is more consice or should i assign each value individually for clarity? 


$call csv2gdx Inputs\base_case.csv id=data_in index =2 values =3..6 useHeader=y output=Inputs\base_case.gdx

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
U(gen,T)   Utilization of each generator for each hour
PlantCost(gen,T)   Cost for each generator and hour
;

POSITIVE VARIABLES U, PlantCost, Cost;



EQUATIONS
* The equation definition block:
Qcap(gen,T)   Equation for utilization of each generator
QDemand(T)   Equation for demand satisfaction
QCost(T)   Equation for total cost for each hour
QTOTCost   Equation for total cost for all hours
QPlant(gen,T)   Equation for cost of each generator and hour
;


Qcap(gen,T)..	U(gen,T) =l=data(gen,'cap'); #MWh
QDemand(T)..	 sum(gen, U(gen,T)) =E= PRD_DATA(T); #MWh 

* Equations for calculating the production cost for each plant based on utilization and cost parameters
QPlant(gen,T)..	PlantCost(gen,T) =E= data(gen,'vom')*U(gen,T) + data(gen,'cost')*U(gen,T)/data(gen,'eff'); # dollars

* Equations for calculating the total cost for each hour and the total cost for all hours
QCost(T)..	Cost(T) =E= sum(gen, PlantCost(gen,T));
QTOTCost..	TOTCost =E= SUM(T, Cost(T));

MODEL CLIMATE /ALL/;
SOLVE CLIMATE USING lp MINIMIZING TOTCost;

DISPLAY QDemand.M, TOTCost.L, U.L;

ExcelResults(T,'DemandMarginal') = QDemand.M(T);
ExcelResults(T,'Solar') = U.L('Solar',T);
ExcelResults(T,'Coal') = U.L('Coal',T);
ExcelResults(T,'Gas') = U.L('Gas',T);

execute_unload 'Results\My_First_DM_results.gdx', ExcelResults;

execute 'gdxxrw Results\My_First_DM_results.gdx output=Results\My_First_DM_results.xlsx squeeze=n par=ExcelResults rng=Hourly!A1';

*dont run results if infesabile 