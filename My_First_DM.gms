$offeolcom
$eolcom #

SETS
            J      List of Plants available
                     /1 , 2, 3/
            T       List of all time Hours
* this means all hours from 1 to 744
                    /1*744/;    

PARAMETERS
C_coal(T)     Cost of coal per unit for each hour
C_gas(T)      Cost of gas per unit for each hour
C_solar(T)    Cost of solar per unit for each hour
PRD_DATA(T)   Input data for production quantity;


C_coal(T) = 7.8; # $/MWhTh
C_gas(T) = 19.8; # $/MWhTh
C_solar(T) = 1;# $/MWhTh

$onEmbeddedCode Connect:
- ExcelReader:
    file: demand.xlsx
    symbols:
      - name: d
        range: in!A2:B745
        rowDimension: 1
        columnDimension: 0
- GAMSWriter:
    symbols: all
$offEmbeddedCode

PRD_DATA(T) = d(T);

VARIABLES
TOTCost(J,T)     Total cost of emissions for all hours
Cost(T)     Total cost for each hour
U_solar(T)     Utilization of solar energy for each hour
U_Coal(T)     Utilization of coal energy for each hour
U_Gas(T)     Utilization of gas energy for each hour

;

POSITIVE VARIABLES U_solar,U_Coal,U_Gas;


EQUATIONS
* The equation definition block:
QUS(T)     Equation for Solar Utililzation 
QCOAL(T)   Equation for coal utilization
QGAS(T)    Equation for gas utilization
QDemand(T)   Equation for demand satisfaction
QCost(T)   Equation for total cost for each hour
QTOTCost   Equation for total cost for all hours
;

QUS(T)..	U_solar(T) =l= 500;
QCOAL(T)..	U_Coal(T) =l= 100;
QGAS(T)..	U_Gas(T) =l= 600;
*Demand with effieicency included 
QDemand(T)..	U_solar(T) + U_Coal(T)*0.4 + U_Gas(T)*0.5 = E = PRD_DATA(T);
* Sum over T across all products combined with the emission coefficient for each year
QCost(T)..	Cost(T) =E= (C_coal(T)*U_Coal(T) +2) + (C_gas(T)*U_Gas(T)+2) + (C_solar(T)*(U_solar(T)/U_solar(T)));
QTOTCost..	TOTCost =E= SUM(T, Cost(T));

MODEL CLIMATE /ALL/;
SOLVE CLIMATE USING DNLP MINIMIZING TOTCost;

DISPLAY INDEX,Cost,TOTCost;
