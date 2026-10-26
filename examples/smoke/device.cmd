File {
  Grid = "smoke_msh.tdr"
  Plot = "smoke_des.tdr"
  Current = "smoke_des.plt"
  Output = "smoke_des.log"
}
Electrode {
  { Name="Left" Voltage=0.0 }
  { Name="Right" Voltage=0.0 }
}
Physics {
  Temperature = 300
  AreaFactor = 1
}
Physics (Material="Silicon") {
  Mobility (DopingDependence)
  Recombination (SRH)
}
Plot { Potential eDensity hDensity eCurrent hCurrent }
Math {
  Method = SUPER
  Number_of_Threads = 1
  Extrapolate
  RelErrControl
  Digits = 5
  Iterations = 30
  ExitOnFailure
}
Solve {
  NewCurrentPrefix = "eq_"
  Coupled(Iterations=50) { Poisson Contact }
  Coupled(Iterations=50) { Poisson Electron Hole Contact }
  NewCurrentPrefix = "bias_"
  Quasistationary(
    InitialStep=1.0 MinStep=1.0 MaxStep=1.0 Increment=1.3 Decrement=2
    Goal { Name="Right" Voltage=0.1 }
  ) { Coupled(Iterations=30) { Poisson Electron Hole Contact } }
  Plot(FilePrefix="smoke_final")
}