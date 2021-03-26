# scqubits: superconducting qubits in Python
#
# This file is part of scqubits.
#
#     Copyright (c) 2019, Jens Koch and Peter Groszkowski
#     All rights reserved.
#
#     This source code is licensed under the BSD-style license found in the
#     LICENSE file in the root directory of this source tree.
"""scqubits is an open-source Python library for simulating superconducting qubits. It is meant to give the user a \
convenient way to obtain energy spectra of common superconducting qubits, plot energy levels as a function of external \
parameters, calculate matrix elements etc. The library further provides an interface to QuTiP, making it easy to work \
with composite Hilbert spaces consisting of coupled superconducting qubits and harmonic modes. Internally, numerics \
within scqubits is carried out with the help of Numpy and Scipy; plotting capabilities rely on Matplotlib."""
#######################################################################################################################

import warnings

import scqubits.settings
# core
from scqubits.core.central_dispatch import CentralDispatch
from scqubits.core.discretization import Grid1d
from scqubits.core.explorer import Explorer
from scqubits.core.flux_qubit import FluxQubit
from scqubits.core.fluxonium import Fluxonium

from scqubits.core.dcp import Dcp
from scqubits.core.dcpl import Dcpl
from scqubits.core.dcpi import Dcpi
from scqubits.core.dcpd import Dcpd
from scqubits.core.dcpr import Dcpr
from scqubits.core.protomon import Protomon
from scqubits.core.protomon_disorder import DisorderProtomon
from scqubits.core.protomon_ver_0 import Protomon_ver_0
from scqubits.core.protomon_full import FullProtomon
from scqubits.core.protomon_full_disorder import DisorderFullProtomon
from scqubits.core.dcpr_dc import Dcpr_dc
from scqubits.core.rhombus import Rhombus
from scqubits.core.dcp_tri import Dcptri


from scqubits.core.harmonic_osc import Oscillator
from scqubits.core.hilbert_space import HilbertSpace, InteractionTerm
from scqubits.core.param_sweep import ParameterSweep, StoredSweep
from scqubits.core.storage import SpectrumData
from scqubits.core.transmon import Transmon, TunableTransmon
from scqubits.core.zeropi import ZeroPi
from scqubits.core.zeropi_full import FullZeroPi
# file IO
from scqubits.io_utils.fileio import read, write

# version
try:
    from scqubits.version import version as __version__
except ImportError:
    warnings.warn("scqubits: missing version information - did scqubits install correctly?", ImportWarning)
