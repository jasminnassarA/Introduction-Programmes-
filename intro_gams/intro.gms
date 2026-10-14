Parameters

    A   
    B   ;

A=3;
B=5;

Variables

    X1      "Explanatory text on the meaning of X1"
    Y       "Explanatory text on the meaning of Y"
    ;

Equations

    QX1     "Explanatory text on the meaning of the equation for X1"
    QY      "Explanatory text on the meaning of the equation for Y"
    ;


QX1..          X1 =L= A;
QY..        Y =E= X1 + B;

MODEL TEST /ALL/;
SOLVE TEST USING DNLP MAXIMIZING Y;
