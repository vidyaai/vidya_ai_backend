"""
Reference list of ACTUAL valid schemdraw elements (version 0.19)
This prevents Claude from hallucinating non-existent element names.

CRITICAL: These are the ONLY valid element names. DO NOT use any other names!
"""

# Based on schemdraw 0.19 documentation
VALID_SCHEMDRAW_ELEMENTS = {
    # PASSIVE COMPONENTS
    "Resistor": "Standard resistor",
    "ResistorVar": "Variable resistor",
    "Thermistor": "Temperature dependent resistor",
    "PhotoResistor": "Light dependent resistor",
    "Capacitor": "Standard capacitor",
    "Capacitor2": "Capacitor with curved plate",
    "CapacitorVar": "Variable capacitor",
    "Inductor": "Standard inductor",
    "Inductor2": "Inductor with core",
    "Crystal": "Crystal oscillator",
    # DIODES
    "Diode": "Standard diode",
    "DiodeShockley": "Shockley diode",
    "Schottky": "Schottky diode",
    "DiodeZener": "Zener diode",
    "Zener": "Zener diode (alias)",
    "LED": "Light emitting diode",
    "Photodiode": "Photodiode",
    # TRANSISTORS - BJT
    "Bjt": "Generic BJT",
    "BjtNpn": "NPN BJT",
    "BjtPnp": "PNP BJT",
    # TRANSISTORS - FET/MOSFET
    "NFet": "N-channel FET (enhancement mode)",
    "PFet": "P-channel FET (enhancement mode)",
    "JFet": "Junction FET",
    "JFetN": "N-channel JFET",
    "JFetP": "P-channel JFET",
    # IMPORTANT: There is NO "Mosfet", "MOSFET", "Pmos", "Nmos", "NMos", "PMos"!
    # For CMOS, use NFet and PFet or draw custom with basic shapes
    # OPERATIONAL AMPLIFIERS
    "Opamp": "Operational amplifier",
    # SOURCES
    "Source": "Generic source",
    "SourceV": "Voltage source",
    "SourceI": "Current source",
    "SourceSin": "Sinusoidal source",
    "SourceSquare": "Square wave source",
    "SourceTriangle": "Triangle wave source",
    "SourceControlled": "Controlled source",
    "SourceControlledV": "Voltage controlled voltage source",
    "SourceControlledI": "Current controlled current source",
    # SWITCHES
    "Switch": "Generic switch",
    "SwitchSpdt": "Single pole double throw",
    "SwitchSpdt2": "SPDT variant",
    "Button": "Push button",
    # METERS
    "Meter": "Generic meter",
    "MeterV": "Voltmeter",
    "MeterI": "Ammeter",
    "MeterA": "Ammeter (alias)",
    "MeterOhm": "Ohmmeter",
    # LOGIC GATES
    "And": "AND gate",
    "Or": "OR gate",
    "Not": "NOT gate (inverter)",
    "Nand": "NAND gate",
    "Nor": "NOR gate",
    "Xor": "XOR gate",
    "Xnor": "XNOR gate",
    "Buf": "Buffer",
    # POWER/GROUND
    "Ground": "Ground symbol",
    "GroundSignal": "Signal ground",
    "GroundChassis": "Chassis ground",
    "Vdd": "Positive supply",
    "Vss": "Negative supply",
    "Antenna": "Antenna",
    # CONNECTIONS
    "Line": "Straight line",
    "Gap": "Gap in line",
    "Dot": "Connection dot",
    "Arrowhead": "Arrow head",
    "Arrow": "Arrow",
    "Label": "Text label",
    # TRANSFORMERS
    "Transformer": "Two-winding transformer",
    # MISC
    "Fuse": "Fuse",
    "Lamp": "Lamp",
    "Motor": "Motor",
    "Speaker": "Speaker",
    "Mic": "Microphone",
}

# Elements that DO NOT EXIST (common mistakes)
INVALID_ELEMENTS = [
    "Mosfet",  # DOES NOT EXIST - use NFet or PFet
    "MOSFET",  # DOES NOT EXIST - use NFet or PFet
    "Nmos",  # DOES NOT EXIST - use NFet
    "NMos",  # DOES NOT EXIST - use NFet
    "Pmos",  # DOES NOT EXIST - use PFet
    "PMos",  # DOES NOT EXIST - use PFet
    "Transistor",  # Too generic - use BjtNpn, BjtPnp, NFet, or PFet
]

# For CMOS circuits, you need to DRAW them manually or use NFet/PFet
CMOS_GUIDANCE = """
For CMOS circuits (push-pull, inverters, logic gates):
1. Use elm.NFet() for NMOS transistors
2. Use elm.PFet() for PMOS transistors
3. Position them with .at() and .anchor()
4. Connect with elm.Line()
5. Add elm.Vdd() and elm.Ground() for power rails

Example CMOS Inverter:
```python
with schemdraw.Drawing(show=False) as d:
    # PMOS on top
    pmos = d.add(elm.PFet().right().anchor('source'))
    d.add(elm.Line().up(0.5).at(pmos.source))
    d.add(elm.Vdd().at(pmos.source))

    # NMOS on bottom
    nmos = d.add(elm.NFet().right().at(pmos.drain).anchor('drain'))
    d.add(elm.Line().down(0.5).at(nmos.source))
    d.add(elm.Ground().at(nmos.source))

    # Input connected to both gates
    d.add(elm.Line().left(0.5).at(pmos.gate))
    d.add(elm.Line().left(0.5).at(nmos.gate))
```
"""


def get_valid_elements_list():
    """Returns formatted list of valid elements"""
    return ", ".join(sorted(VALID_SCHEMDRAW_ELEMENTS.keys()))


def get_common_elements():
    """Returns the most commonly used elements"""
    common = [
        "Resistor",
        "Capacitor",
        "Inductor",
        "Diode",
        "BjtNpn",
        "BjtPnp",
        "NFet",
        "PFet",
        "Opamp",
        "SourceV",
        "SourceI",
        "Ground",
        "Vdd",
        "And",
        "Or",
        "Not",
        "Nand",
        "Nor",
    ]
    return ", ".join(common)
