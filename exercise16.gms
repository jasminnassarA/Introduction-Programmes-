Parameters
    A         "size in hectors of the field"
    Cattle0   "initial number of cattle in the field"
    taxcoef   "tax for each currency unit of tax imposed"
    benefit   "social beneficiary activity"
    cost      "damage per hector due to grazing";

* Assiging parameters values
A=1000;
Cattle0 = 2000;
taxcoef = -50;
benefit = 50;
cost = 24;

Variables
    tax          "cost"
    damage      "damage per hector due to grazing"
    st_rate      "stocking rate = number of cattle per hector"
    cattle       "number of cattle in the field"
    obj          "objective function"
    ;

Positive Variables tax,cattle,st_rate,damage;

Equations
    eq_cat     "Explanatory text on the meaning of the equation for X1"
    eq_sr     "Explanatory text on the meaning of the equation for X2"
    eq_dam      "Explanatory text on the meaning of the equation for Y"
    eq_obj
    ;

eq_cat..    cattle =E= cattle0 + taxcoef*tax;
eq_sr..     st_rate =E= cattle/A;
eq_dam..    damage =E= cost*st_rate*st_rate*A;
eq_obj..    obj =E= (benefit - tax)*cattle - damage;

tax.fx = 0;

MODEL TEST /ALL/;
SOLVE TEST USING DNLP MAXIMIZING obj;