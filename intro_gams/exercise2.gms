$offeolcom
$eolcom #

SETS
           SOL       List of all solves
                     /"1st solve", "2nd solve", "3rd solve"/ 
            J      List of all elements
                     /1 , 2, 3/
            T       List of all time periods
* this means all years from 2000 to 2004
                    /2000*2004/;    

PARAMETERS
RES(SOL,T)   The result of the solvers
COEF(J,T)    Emission coefficient CO2 for each year
PRD_DATA(J,T)   Input data for production quantity
OTHER(T)   Emissions of other greenhouse gasses for each year
INDEX(T)   Index for time periods;


*now these are time dependent parameters, so we can assign values for each year
OTHER(T) = 5;

TABLE DATA(J,T)     Input data for PRD
          2000      2001      2002      2003      2004
1         10        11        12        13        14
2         50        52        54        56        58
3         40        42        44        46        48;

PRD_DATA(J,T) = DATA(J,T);

TABLE COEF_DATA(J,T)     Coefficient for each product
          2000      2001      2002      2003      2004
1         0.01      0.01      0.01      0.01      0.01
2         0.04       0.04     0.04      0.04      0.04     
3         0.025      0.025    0.025     0.025     0.025;

COEF(J,T) = COEF_DATA(J,T);

coef("1",T) = 0.01*(0.99**(ORD(T)-1));
coef("2",T) = 0.04*(0.99**(ORD(T)-1));  
coef("3",T) = 0.025*(0.99**(ORD(T)-1));

INDEX(T) = (ORD(T)-1)/(CARD(T)-1);

VARIABLES

CO2(T)	    Emissions of CO2
PRD(J,T)	    Production quantity
EMIS(T)	 Total emissions of greenhouse gasses
TOTEMIS	Total emissions of greenhouse gasses for all years
DAM(J,T)	Damage costs for each product and year
alpha   Weighting factor for CO2 emissions
;

POSITIVE VARIABLES CO2,PRD,EMIS;

alpha.FX = 0.5;

PRD.LO("1",T) = 12;
PRD.FX("3","2000") = 45;

EMIS.L(T) = 6;
CO2.L(T) = 1;

EQUATIONS
* The equation definition block:
QPRD(J,T)	Equation for economic production
QCO2(T)	Equation for CO2 emissions
QEMIS(T)	Equation for total climate emissions
QTOTEMIS	Equation for total emissions
QDAM(J,T)	Equation for damage costs
;

QPRD(J,T)..	PRD(J,T) =G= ((1 - DAM(J,T))**2)*(PRD_DATA(J,T));
* Sum over T across all products combined with the emission coefficient for each year
QCO2(T)..	CO2(T) =E= SUM(J,COEF(J,T)*PRD(J,T)); 
QEMIS(T).. EMIS(T) =E= CO2(T)*alpha*2 + OTHER(T)*(1-alpha)*2;
*sum of EMIS over time
QTOTEMIS..	TOTEMIS =E= SUM(T, EMIS(T)); 
QDAM(J,T)..   DAM(J,T) =E= 0.05+0.05$(PRD_DATA(J,T-1)>50);

MODEL CLIMATE /ALL/;
LOOP(SOL,
         SOLVE CLIMATE USING DNLP MINIMIZING TOTEMIS;
         RES(SOL,T) = EMIS.L(T);
         PRD.LO('3','2000')= -INF;
         PRD.UP('3','2000')= +INF;         
         OTHER(T) = OTHER(T)+2; 
);  
DISPLAY RES,INDEX;

execute_UNLOAD '3_2_21.gdx', res;
execute 'gdxxrw.exe 3_2_21.gdx par=res';
*this works becouse it bypasses think cell
*execute 'gdxxrw.exe 3_2_21.gdx output=3_2_21.xlsx par=res rng=Results!A1';