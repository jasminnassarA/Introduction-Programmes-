* My attempt at trying to use csv files for simplicity instead of manually entering data
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
            outfield Output columns
                    /DemandMarginal,Demand,Solar,Coal,Gas,Wind/; #cost($/MWhTh),Cap (MW),eff (MWh/MWhTh),vom($/MWh)


PARAMETERS
data(gen,f) Input data for cost, capacity, efficiency, and variable O&M for each generator
PRD_DATA(T) Input data for production quantity
d(T) Input data for demand for each hour
Load_factor(T,gen) Input data for load factor for each hour
Ramp(gen,T)   Ramp for each generator and hour
ExcelResults(T,outfield) Values exported to Excel;



$call csv2gdx Inputs\Renewable_intermit.csv id=data_in index =1 values =2..7 useHeader=y output=Inputs\Renewable_intermit.gdx

$gdxin Inputs\Renewable_intermit.gdx
$load data = data_in
$gdxin

* Optional overrides passed from the dashboard (defaults keep the original behaviour)
$if not set outdir $set outdir Results
$if set solarCap data('Solar','cap') = %solarCap%;
$if set coalCap data('Coal','cap') = %coalCap%;
$if set gasCap data('Gas','cap') = %gasCap%;
$if set windCap data('Wind','cap') = %windCap%;


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

VARIABLES
TOTCost     Total cost of emissions for all hours
Cost(T)     Total cost for each hour
U(gen,T)   Utilization of each generator for each hour
PlantCost(gen,T)   Cost for each generator and hour
Ramp_U(gen,T)   Ramp utilization for each generator and hour
Ramp_D(gen,T)   Ramp down utilization for each generator and hour
;

POSITIVE VARIABLES U, PlantCost, Cost,Ramp_U,Ramp_D;




EQUATIONS
* The equation definition block:
Qcap(gen,T)   Equation for utilization of each generator
QDemand(T)   Equation for demand satisfaction
QCost(T)   Equation for total cost for each hour
QTOTCost   Equation for total cost for all hours
QPlant(gen,T)   Equation for cost of each generator and hour
QVol_ramp_U(gen,T)   Equation for ramp volume for each generator and hour
QVol_ramp_D(gen,T)   Equation for ramp down volume for each generator and hour
QRamp_U(gen,T)   Equation for ramp up for each generator and hour
QRamp_D(gen,T)   Equation for ramp down for each generator and hour

;

*this means that the equation only applies for time periods greater than 1 so that ramping up from 0 isnt considered
QVol_ramp_U(gen,T)$(ord(T)>1).. Ramp_U(gen,T) =g= U(gen,T) - U(gen,T-1); #MWh
QVol_ramp_D(gen,T)$(ord(T)>1).. Ramp_D(gen,T) =g= U(gen,T-1) - U(gen,T); #MWh

QRamp_U(gen,T)$(ord(T)>1).. Ramp_U(gen,T) =l= Ramp(gen,T); #MWh
QRamp_D(gen,T)$(ord(T)>1).. Ramp_D(gen,T) =l= Ramp(gen,T); #MWh

Qcap(gen,T)..	U(gen,T) =l=data(gen,'cap')*Load_factor(T,gen); #MWh
QDemand(T)..	 sum(gen, U(gen,T)) =E= PRD_DATA(T); #MWh 

* Equations for calculating the production cost for each plant based on utilization and cost parameters
QPlant(gen,T)..	PlantCost(gen,T) =E= data(gen,'vom')*U(gen,T) + data(gen,'cost')*U(gen,T)/data(gen,'eff') + data(gen,'ramp_cost')*(Ramp_U(gen,T) + Ramp_D(gen,T)); # dollars; # dollars

* Equations for calculating the total cost for each hour and the total cost for all hours
QCost(T)..	Cost(T) =E= sum(gen, PlantCost(gen,T));
QTOTCost..	TOTCost =E= SUM(T, Cost(T));

MODEL CLIMATE /ALL/;
SOLVE CLIMATE USING lp MINIMIZING TOTCost;

DISPLAY QDemand.M, TOTCost.L, U.L;

ExcelResults(T,'DemandMarginal') = QDemand.M(T);
ExcelResults(T,'Demand') = d(T); #MWh
ExcelResults(T,'Solar') = U.L('Solar',T);
ExcelResults(T,'Coal') = U.L('Coal',T);
ExcelResults(T,'Gas') = U.L('Gas',T);
ExcelResults(T,'Wind') = U.L('Wind',T);

execute_unload '%outdir%\ramping.gdx', ExcelResults;

$if not set noxlsx execute 'gdxxrw %outdir%\ramping.gdx output=%outdir%\ramping.xlsx squeeze=n par=ExcelResults rng=Hourly!A1';


*dont run results if infesabile
