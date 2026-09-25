from dataclasses import dataclass,field
@dataclass
class ObservationWindow: service:str; features:dict; slopes:dict=field(default_factory=dict)
@dataclass
class CurrentSituation: service:str; failure_class:str; dependency:str|None; trajectory:dict
