# test_explorer.py
# meant to be run with 'pytest'
#
# This file is part of scqubits: a Python package for superconducting qubits,
# Quantum 5, 583 (2021). https://quantum-journal.org/papers/q-2021-11-17-583/
#
#    Copyright (c) 2019 and later, Jens Koch and Peter Groszkowski
#    All rights reserved.
#
#    This source code is licensed under the BSD-style license found in the
#    LICENSE file in the root directory of this source tree.
############################################################################

import numpy as np

import scqubits as scq


def test_explorer():
    qbt = scq.Fluxonium(
        EJ=2.55, EC=0.72, EL=0.12, flux=0.0, cutoff=110, truncated_dim=9
    )

    osc = scq.Oscillator(E_osc=4.0, truncated_dim=5)

    hilbertspace = scq.HilbertSpace([qbt, osc])
    hilbertspace.add_interaction(
        g_strength=0.2, op1=qbt.n_operator, op2=osc.creation_operator, add_hc=True
    )
    param_name = r"$\Phi_{ext}/\Phi_0$"
    param_vals = np.linspace(-0.5, 0.5, 101)

    subsys_update_list = [qbt]

    def update_hilbertspace(param_val):
        qbt.flux = param_val

    sweep = scq.ParameterSweep(
        paramvals_by_name={param_name: param_vals},
        evals_count=10,
        hilbertspace=hilbertspace,
        subsys_update_info={param_name: [qbt]},
        update_hilbertspace=update_hilbertspace,
    )
    explorer = scq.Explorer(sweep=sweep, evals_count=10)
    explorer.interact()
