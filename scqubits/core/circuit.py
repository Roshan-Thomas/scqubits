# circuit.py
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

import re
import warnings
from typing import Any, Dict, List, Literal, Optional, Tuple, Union, Callable
# define a type for recursive lists using forward reference and alias
RecursiveList = List[Union[int, "RecursiveList"]]

import numpy as np
import sympy as sm
from matplotlib import pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from numpy import ndarray
from sympy import latex

try:
    from IPython.display import Latex, display
except ImportError:
    _HAS_IPYTHON = False
else:
    _HAS_IPYTHON = True

import scqubits.core.discretization as discretization
import scqubits.core.central_dispatch as dispatch
import scqubits.core.qubit_base as base
import scqubits.io_utils.fileio_serializers as serializers

from scqubits import settings
from scqubits.core.circuit_utils import (
    get_trailing_number,
    is_potential_term,
)
from scqubits.core.symbolic_circuit import Branch, SymbolicCircuit
from scqubits.io_utils.fileio import IOData
from scqubits.io_utils.fileio_serializers import dict_serialize
from scqubits.utils.misc import (
    flatten_list,
    number_of_lists_in_list,
)

from scqubits.core.circuit_routines import CircuitRoutines
from scqubits.core.circuit_noise import NoisyCircuit


class Subsystem(
    CircuitRoutines,
    base.QubitBaseClass,
    serializers.Serializable,
    dispatch.DispatchClient,
    NoisyCircuit,
):
    """
    Defines a subsystem for a circuit or a subsystem.

    Parameters
    ----------
    parent:
        The instance under which the new subsystem is defined. Can be either a Circuit
        instance or a Subsystem instance.
    hamiltonian_symbolic:
        The symbolic expression which defines the Hamiltonian for the new subsystem.
    system_hierarchy:
        The system hierarchy within the new subsystem; has to be None when the
        subsystem does not have any subsystem. Set to None by default.
        TODO: do we need to show an example? Refer to doc.
    subsystem_trunc_dims:
        The truncated dimensions for the subsystems within the new subsystem;
        has to None when the subsystem does not have any subsystem. Set to None
        by default.
        TODO: do we need to show an example?
    truncated_dim:
        The truncated dimension for the current subsystem. Set to 10 by default.
    """

    def __init__(
        self,
        parent: Union["Subsystem", "Circuit"],
        hamiltonian_symbolic: sm.Expr,
        system_hierarchy: Optional[RecursiveList] = None,
        subsystem_trunc_dims: Optional[RecursiveList] = None,
        truncated_dim: Optional[int] = 10,
        evals_method: Union[Callable, str, None] = None,
        evals_method_options: Union[dict, None] = None,
        esys_method: Union[Callable, str, None] = None,
        esys_method_options: Union[dict, None] = None,
    ):
        # attribute used in protecting the class from erroneous addition of new attributes
        # __setattr__ method is overwritten for Circuit and SubSystem classes (see circuit_routines.py),
        # therefore _frozen needs to be set using the Python default __setattr__ method
        object.__setattr__(self, "_frozen", False)

        base.QubitBaseClass.__init__(
            self,
            id_str=None,
            evals_method=evals_method,
            evals_method_options=evals_method_options,
            esys_method=esys_method,
            esys_method_options=esys_method_options,
        )

        # This class does not yet support custom diagonalization options, but these
        # still have to be defined
        self.evals_method = None
        self.evals_method_options = None
        self.esys_method = None
        self.esys_method_options = None

        self.system_hierarchy = system_hierarchy
        self.truncated_dim = truncated_dim
        self.subsystem_trunc_dims = subsystem_trunc_dims
        self.is_child = True
        self.parent = parent
        self.hamiltonian_symbolic = hamiltonian_symbolic

        # take over parent's default grids
        self._default_grid_phi = self.parent._default_grid_phi
        # TODO change the name for `_default_grid_phi`? We need to fix whether we want to use `phi` or `theta`
        # for flux/phase
        # notice that we have already method `discretized_phi_range`
        # Sai's reasoning: phi is more familiar with the community
        # maybe flux is a better choice?
        # check with Jens.
        # new name: discretization_range? discretization_min_max? discretization_bounds?

        # initialize the two attributes for storing junction potential
        self.junction_potential = None

        # this _make_property method is implemented in CircuitRoutines class
        # here, a property `ext_basis` is created for the new subsystem, which is the same as the parent's
        # `ext_basis` property
        self._make_property(
            "ext_basis", getattr(self.parent, "ext_basis"), "update_ext_basis"
        )
        # find out external flux and offset charge sympy expressions in the new subsystem
        # by looking up the parent's external fluxes and offset charges and checking whether they are
        # in the new subsystem's Hamiltonian
        self.external_fluxes = [
            var
            for var in self.parent.external_fluxes
            if var in self.hamiltonian_symbolic.free_symbols
        ]
        self.offset_charges = [
            var
            for var in self.parent.offset_charges
            if var in self.hamiltonian_symbolic.free_symbols
        ]
        # find out symbolic parameters in the new subsystem by looking up the parent's symbolic parameters
        # and checking whether they are in the new subsystem's Hamiltonian
        # Sai: make symbolic_params a list as well, store all the symbolic parameter values as properties/attributes
        # TODO: change it to list, and whenever we fetch values, use __getattr__ to get the value.
        self.symbolic_params: Dict[sm.Expr, float] = {
            var: self.parent.symbolic_params[var]
            for var in self.parent.symbolic_params
            if var in self.hamiltonian_symbolic.free_symbols
        }

        # obtain variable indices and cutoffs in the subsystem by looking up the parent's variable indices and
        # cutoffs and checking whether they are in the new subsystem's Hamiltonian
        self.var_index_list: List[int] = []
        for var_name in self.operator_names_in_hamiltonian_symbolic():
            var_index = get_trailing_number(var_name)
            if var_index not in self.var_index_list and var_index is not None:
                self.var_index_list.append(var_index)
        self.var_index_list.sort()

        # group subsystem variable indices by their variable categories by looking up parent's var_categories
        self.var_categories: Dict[str, List[int]] = {}
        for var_type in self.parent.var_categories:
            self.var_categories[var_type] = [
                var_index
                for var_index in self.parent.var_categories[var_type]
                if var_index in self.var_index_list
            ]

        # generate cutoff names for the new subsystem
        self.cutoff_names: List[str] = []
        for var_type in self.var_categories.keys():
            if var_type == "periodic":
                for var_index in self.var_categories["periodic"]:
                    self.cutoff_names.append(f"cutoff_n_{var_index}")
            if var_type == "extended":
                for var_index in self.var_categories["extended"]:
                    self.cutoff_names.append(f"cutoff_ext_{var_index}")

        # carry forward the discretized phi basis range from the parent
        self.discretized_phi_range: Dict[int, Tuple[float]] = {
            idx: self.parent.discretized_phi_range[idx]
            for idx in self.parent.discretized_phi_range
            if idx in self.var_index_list
        }

        # store the potential terms separately
        # and bring the potential into the same form as for the class Circuit
        # all cosθ<i> and sinθ<i> terms are replaced by sm.cos(1.0 * θ<i>) and sm.sin(1.0 * θ<i>)
        # and all I terms are replaced by 1/(2*pi)
        # TODO: what was I? Was I relate to external flux? This is related to the const in cos and sin
        # Sai: need to refactor the matter with 2pi
        potential_symbolic = 0 * sm.symbols("x")
        for term in self.hamiltonian_symbolic.as_ordered_terms():
            if is_potential_term(term):
                potential_symbolic += term
        for i in self.var_index_list:
            potential_symbolic = (
                potential_symbolic.replace(
                    sm.symbols(f"cosθ{i}"), sm.cos(1.0 * sm.symbols(f"θ{i}"))
                )
                .replace(sm.symbols(f"sinθ{i}"), sm.sin(1.0 * sm.symbols(f"θ{i}")))
                .subs(sm.symbols("I"), 1 / (2 * np.pi))
            )
        self.potential_symbolic = potential_symbolic

        # I removed the `system_hierarchy != []` here as it is always true
        self.hierarchical_diagonalization: bool = (
            number_of_lists_in_list(system_hierarchy) > 0
        )

        # TODO: why if only one variable and harmonic basis, then dense matrices?
        # if I have two external variables, then sparse matrices?
        # Sai: we would have many zeros for systems with dofs > 2
        # followup: is it true for inductively coupled fluxonia?
        if len(self.var_index_list) == 1 and self.ext_basis == "harmonic":
            self.type_of_matrices = "dense"
        else:
            self.type_of_matrices = "sparse"

        # initialize `_init_params` as required by plot_evals_vs_paramvals
        self._init_params = []

        # attributes for purely harmonic
        # TODO: not all subsystems are purely harmonic, do we have to have this attribute for
        # non-purely-harmonic subsystems?
        # Sai: consider about removing it for non-purely-harmonic subsystems
        self.normal_mode_freqs = []

        # call `_configure` and then freeze the subsystem from adding new attributes
        self._configure()
        self._frozen = True

    def _configure(self) -> None:
        """
        Method which is used to initiate the subsystem instance.
        """
        self._frozen = False
        # Generate properties for circuit element symbolic parameters (EJ, EC, EL)
        # and get properties values from parent
        # TODO double check if I understood `symbolic_params` correctly, I rewrote the iterator
        # in a way that it looks natural for a dict
        # Sai: depends on how we modify symbolic_params
        for param in self.symbolic_params.keys():
            self._make_property(
                param.name, getattr(self.parent, param.name), "update_param_vars"
            )
        # Generate properties for external fluxes and offset charges and get their values from
        # parent
        for flux in self.external_fluxes:
            self._make_property(
                flux.name,
                getattr(self.parent, flux.name),
                "update_external_flux_or_charge",
            )
        for offset_charge in self.offset_charges:
            self._make_property(
                offset_charge.name,
                getattr(self.parent, offset_charge.name),
                "update_external_flux_or_charge",
            )
        # Generate properties for cutoffs and get their values from parent
        for cutoff_str in self.cutoff_names:
            self._make_property(
                cutoff_str, getattr(self.parent, cutoff_str), "update_cutoffs"
            )

        # Check if subsystem hamiltonian is purely harmonic
        # if so, then switch the external basis to harmonic and diagonalize the hamiltonian
        # TODO need to think about its consistency with other parts of the code where we specify
        # basis types
        # Need to cook up an example to see the impact of this change
        # should we inform user which basis is used?
        # currently the `_ext_basis` of the child takes the precedence over the parent when
        # we do the diagonalization.
        if self._is_expression_purely_harmonic(self.hamiltonian_symbolic):
            self.is_purely_harmonic = True
            self._ext_basis = (
                "harmonic"  # using harmonic oscillator basis for purely harmonic
            )
            self._diagonalize_purely_harmonic_hamiltonian()
        else:
            self.is_purely_harmonic = False

        # set a `self.vars` attribute which is a dict of all variables in the subsystem
        self._set_vars()

        # generate symbolic hamiltonian which is ready for numerical evaluation
        self.generate_hamiltonian_sym_for_numerics()

        if self.hierarchical_diagonalization:
            # initialize the attribute to keep track of updated subsystem indices
            # TODO what is the need for this attribute? Do we need this for the following
            # lines of code before the assigment line later?
            # self.affected_subsystem_indices = []

            # generate subsystems and interactions, perform checks on truncation indices
            self.generate_subsystems()
            self.update_interactions()
            self._check_truncation_indices()
            # create operator methods
            self.operators_by_name = self.set_operators()
            self.affected_subsystem_indices = list(range(len(self.subsystems)))
        else:
            # only create operator methods if not doing hierarchical diagonalization
            self.operators_by_name = self.set_operators()

        if self.hierarchical_diagonalization:
            # set up central dispatch for the sync status of the subsystems
            # when the child is out of sync with the parent, then `_out_of_sync` is set to `True`
            self._out_of_sync = False
            dispatch.CENTRAL_DISPATCH.register("CIRCUIT_UPDATE", self)
        self._frozen = True


class Circuit(
    CircuitRoutines,
    base.QubitBaseClass,
    serializers.Serializable,
    dispatch.DispatchClient,
    NoisyCircuit,
):
    """
    Class for analysis of custom superconducting circuits.

    Parameters
    ----------
    input_string:
        If `from_file = False`, expected be a yaml string describing the circuit.
        If `from_file = True`, expected to be a path of a file that stores the yaml string for the circuit.
    from_file:
        If `True`, a file path should be provided for `input_string`.
        If `False`, a yaml string describing the circuit is expected for `input_string`.
        Set to `False` by default.
    basis_completion:
        Either "heuristic" or "canonical". Defines the matrix used for completing the
        extended degrees of freedom part of the transformation matrix. Sometimes one of
        these options may lead to a simpler symbolic Hamiltonian than the other. Set to
        "heuristic" by default.
        TODO need a better description for this. (Sai)
    ext_basis:
        Either "discretized" or "harmonic", which chooses whether to use discretized
        flux or harmonic oscillator basis for extended degrees of freedom. Set to "discretized"
        by default.
    is_flux_dynamic:
        If `True`, the flux allocation is done by assuming that flux is time dependent. The option to change
        the closure branches is then disabled. Set to `False` by default.
    initiate_sym_calc:
        attribute to initiate Circuit instance, set to by default `True`
        TODO decide whether or not to keep this argument (remove it. remove from all the inits, extinguish it)
    truncated_dim:
        The truncated dimension for this Circuit instance. Needed when this Circuit instance is used for
        composing a composite system using the HilbertSpace class. Set to `None` by default.
    symbolic_hamiltonian:
        A sympy expression for the symbolic circuit Hamiltonian. If both the yaml string for the circuit and the
        symbolic Hamiltonian provided, the yaml string for the circuit is neglected.
    symbolic_param_dict:
        A dictionary {"<symbolic parameter name>": <value>} for initial values of parameters in `symbolic_hamiltonian`.
        Ignored if `symbolic_hamiltonian = None`.

    TODO Sai: check if I am not writing nonsense for the symbolic_param_dict and symbolic_hamiltonian
    """

    def __init__(
        self,
        input_string: Optional[str] = None,
        from_file: bool = False,
        basis_completion: Literal["heuristic", "canonical"] = "heuristic",
        ext_basis: Literal[
            "discretized", "harmonic"
        ] = "discretized",  # make similar changes in other places TODO
        is_flux_dynamic: bool = False,
        initiate_sym_calc: bool = True,
        truncated_dim: int = 10,
        symbolic_param_dict: Dict[str, float] = None,
        symbolic_hamiltonian: sm.Expr = None,
        evals_method: Union[Callable, str, None] = None,
        evals_method_options: Union[dict, None] = None,
        esys_method: Union[Callable, str, None] = None,
        esys_method_options: Union[dict, None] = None,
    ):
        # attribute used in protecting the class from erroneous addition of new attributes
        # __setattr__ method is overwritten for Circuit and SubSystem classes (see circuit_routines.py),
        # therefore _frozen needs to be set using the default __setattr__ method
        object.__setattr__(self, "_frozen", False)
        base.QubitBaseClass.__init__(
            self,
            id_str=None,
            evals_method=evals_method,
            evals_method_options=evals_method_options,
            esys_method=esys_method,
            esys_method_options=esys_method_options,
        )

        if not symbolic_hamiltonian:
            self._init_from_yaml(
                input_string=input_string,
                from_file=from_file,
                basis_completion=basis_completion,
                ext_basis=ext_basis,
                is_flux_dynamic=is_flux_dynamic,
                initiate_sym_calc=initiate_sym_calc,
                truncated_dim=truncated_dim,
            )
        else:
            self._init_from_symbolic_hamiltonian(
                symbolic_hamiltonian=symbolic_hamiltonian,
                symbolic_param_dict=symbolic_param_dict,
                initiate_sym_calc=initiate_sym_calc,
                truncated_dim=truncated_dim,
                ext_basis=ext_basis,
            )

    def _init_from_symbolic_hamiltonian(
        self,
        symbolic_hamiltonian: sm.Expr,
        symbolic_param_dict: Dict[str, float],
        initiate_sym_calc: bool,
        truncated_dim: int,
        ext_basis: str,
    ):
        self.hamiltonian_symbolic = symbolic_hamiltonian

        self.symbolic_params = {}
        for param_str in symbolic_param_dict:
            self.symbolic_params[sm.symbols(param_str)] = symbolic_param_dict[param_str]

        sm.init_printing(pretty_print=False, order="none")
        self.is_child = False

        self._make_property("ext_basis", ext_basis, "update_ext_basis")
        self.truncated_dim: int = truncated_dim
        self.system_hierarchy: list = None
        self.subsystem_trunc_dims: list = None
        self.operators_by_name = None

        self.discretized_phi_range: Dict[int, Tuple[float, float]] = {}
        self.cutoff_names: List[str] = []

        # setting default grids for plotting
        self._default_grid_phi: discretization.Grid1d = discretization.Grid1d(
            -6 * np.pi, 6 * np.pi, 200
        )

        self.type_of_matrices: str = (
            "sparse"  # type of matrices used to construct the operators
        )

        # needs to be included to make sure that plot_evals_vs_paramvals works
        self._init_params = []
        self._out_of_sync = False  # for use with CentralDispatch
        self._user_changed_parameter = (
            False  # to track parameter changes in the circuit
        )

        if initiate_sym_calc:
            self.configure()
        self._frozen = True
        dispatch.CENTRAL_DISPATCH.register("CIRCUIT_UPDATE", self)

    def _init_from_yaml(
        self,
        input_string: str,
        from_file: bool = False,
        basis_completion="heuristic",
        ext_basis: str = "discretized",
        is_flux_dynamic: bool = False,
        initiate_sym_calc: bool = True,
        truncated_dim: int = None,
    ):
        """
        # TODO rewording this docstring
        Wrapper to Circuit __init__ to create a class instance. This is deprecated and
        will not be supported in future releases.

        Parameters
        ----------
        input_string:
            String describing the number of nodes and branches connecting then along
            with their parameters
        from_file:
            When set to true, a file name should be provided to `input_string`, else
            the circuit graph description in YAML should be provided as a string.
            Set to True by default.
        basis_completion:
            either "heuristic" or "canonical", defines the matrix used for completing
            the transformation matrix. Sometimes used to change the variable
            transformation to result in a simpler symbolic Hamiltonian, by default
            "heuristic"
        ext_basis:
            can be "discretized" or "harmonic" which chooses whether to use discretized
            phi or harmonic oscillator basis for extended variables,
            by default "discretized"
        initiate_sym_calc:
            attribute to initiate Circuit instance, by default `True`
        truncated_dim:
            truncated dimension if the user wants to use this circuit instance in
            HilbertSpace, by default `None`
        is_flux_dynamic: bool
            set to False by default. Indicates if the flux allocation is done by assuming that flux is time dependent. When set to True, it disables the
            option to change the closure branches.
        """
        # warnings.warn(
        #     "Initializing Circuit instances with `from_yaml` will not be "
        #     "supported in the future. Use `Circuit` to initialize a Circuit instance.",
        #     np.VisibleDeprecationWarning,
        # )
        if basis_completion not in ["heuristic", "canonical"]:
            raise Exception(
                "Invalid choice for basis_completion: must be 'heuristic' or "
                "'canonical'."
            )

        symbolic_circuit = SymbolicCircuit.from_yaml(
            input_string,
            from_file=from_file,
            basis_completion=basis_completion,
            initiate_sym_calc=True,
            is_flux_dynamic=is_flux_dynamic,
        )

        # This class does not yet support custom diagonalization options, but these
        # still have to be defined
        self.evals_method = None
        self.evals_method_options = None
        self.esys_method = None
        self.esys_method_options = None

        sm.init_printing(pretty_print=False, order="none")
        self.is_child = False
        self.symbolic_circuit: SymbolicCircuit = symbolic_circuit

        self._make_property("ext_basis", ext_basis, "update_ext_basis")
        self.truncated_dim: int = truncated_dim
        self.system_hierarchy: list = None
        self.subsystem_trunc_dims: list = None
        self.operators_by_name = None

        self.discretized_phi_range: Dict[int, Tuple[float, float]] = {}
        self.cutoff_names: List[str] = []

        # setting default grids for plotting
        self._default_grid_phi: discretization.Grid1d = discretization.Grid1d(
            -6 * np.pi, 6 * np.pi, 200
        )

        self.type_of_matrices: str = (
            "sparse"  # type of matrices used to construct the operators
        )
        # copying all the required attributes
        required_attributes = [
            "branches",
            "closure_branches",
            "external_fluxes",
            "ground_node",
            "hamiltonian_symbolic",
            "input_string",
            "is_grounded",
            "lagrangian_node_vars",
            "lagrangian_symbolic",
            "nodes",
            "offset_charges",
            "potential_symbolic",
            "potential_node_vars",
            "symbolic_params",
            "transformation_matrix",
            "var_categories",
        ]
        for attr in required_attributes:
            setattr(self, attr, getattr(self.symbolic_circuit, attr))

        # needs to be included to make sure that plot_evals_vs_paramvals works
        self._init_params = []
        self._out_of_sync = False  # for use with CentralDispatch
        self._user_changed_parameter = (
            False  # to track parameter changes in the circuit
        )

        if initiate_sym_calc:
            self.configure()
        self._frozen = True
        dispatch.CENTRAL_DISPATCH.register("CIRCUIT_UPDATE", self)

    def set_discretized_phi_range(
        self, var_indices: Tuple[int], phi_range: Tuple[float]
    ) -> None:
        """
        Sets the flux range for discretized flux basis when ext_basis is set to
        'discretized'.

        Parameters
        ----------
        var_indices:
            list of var_indices whose range needs to be changed
        phi_range:
            The desired range for each of the discretized phi variables
        """
        if self.ext_basis != "discretized":
            raise Exception(
                "Discretized phi range is only used when ext_basis is set to "
                "'discretized'."
            )
        for var_index in var_indices:
            if var_index not in self.var_categories["extended"]:
                raise Exception(
                    f"Variable with index {var_index} is not an extended variable."
                )
            self.discretized_phi_range[var_index] = phi_range
        self.operators_by_name = self.set_operators()

    def dict_for_serialization(self):
        # setting the __init__params attribute
        modified_attrib_keys = (
            [param.name for param in self.symbolic_params]
            + [flux.name for flux in self.external_fluxes]
            + [offset_charge.name for offset_charge in self.offset_charges]
            + self.cutoff_names
            + ["system_hierarchy", "subsystem_trunc_dims", "transformation_matrix"]
        )
        modified_attrib_dict = {key: getattr(self, key) for key in modified_attrib_keys}
        init_params_dict = {}
        init_params_list = ["ext_basis", "input_string", "truncated_dim"]

        for param in init_params_list:
            init_params_dict[param] = getattr(self, param)
        init_params_dict["from_file"] = False
        init_params_dict["basis_completion"] = self.symbolic_circuit.basis_completion

        # storing which branches are used for closure_branches
        closure_branches_data = []
        for branch in self.closure_branches:  # store symbolic param as string
            branch_params = branch.parameters.copy()
            for param in branch_params:
                if isinstance(branch_params[param], sm.Symbol):
                    branch_params[param] = branch_params[param].name
            branch_data = [
                branch.nodes[0].index,
                branch.nodes[1].index,
                branch.type,
                branch_params,
            ]
            closure_branches_data.append(branch_data)
        modified_attrib_dict["closure_branches_data"] = closure_branches_data

        init_params_dict["_modified_attributes"] = modified_attrib_dict
        return init_params_dict

    def serialize(self):
        iodata = dict_serialize(self.dict_for_serialization())
        iodata.typename = type(self).__name__
        return iodata

    @classmethod
    def deserialize(cls, iodata: "IOData") -> "Circuit":
        """
        Take the given IOData and return an instance of the described class, initialized
        with the data stored in io_data.

        Parameters
        ----------
        iodata:

        Returns
        -------
            Circuit instance
        """
        init_params = iodata.as_kwargs()
        _modified_attributes = init_params.pop("_modified_attributes")

        circuit = cls(**init_params)

        closure_branches = [
            circuit._find_branch(*branch_data)
            for branch_data in _modified_attributes["closure_branches_data"]
        ]
        del _modified_attributes["closure_branches_data"]

        # removing parameters that are not defined
        configure_attribs = [
            # "transformation_matrix",
            "system_hierarchy",
            "subsystem_trunc_dims",
        ]
        configure_attribs = [
            attrib for attrib in configure_attribs if attrib in _modified_attributes
        ]

        circuit.configure(
            closure_branches=closure_branches,
            **{key: _modified_attributes[key] for key in configure_attribs},
        )
        # modifying the attributes if necessary
        for attrib in _modified_attributes:
            if attrib not in configure_attribs:
                setattr(circuit, "_" + attrib, _modified_attributes[attrib])
        if circuit.hierarchical_diagonalization:
            circuit.generate_subsystems()
            circuit.update_interactions()
        return circuit

    def _find_branch(
        self, node_id_1: int, node_id_2: int, branch_type: str, branch_params: dict
    ):
        for branch in self.symbolic_circuit.branches:
            branch_node_ids = [node.index for node in branch.nodes]
            branch_params_circ = branch.parameters.copy()
            for param in branch_params_circ:
                if isinstance(branch_params_circ[param], sm.Symbol):
                    branch_params_circ[param] = branch_params_circ[param].name
            if node_id_1 not in branch_node_ids or node_id_2 not in branch_node_ids:
                continue
            if branch.type != branch_type:
                continue
            if branch_params != branch_params_circ:
                continue
            return branch
        return None

    @staticmethod
    def default_params() -> Dict[str, Any]:
        return {}

    def _clear_unnecessary_attribs(self):
        """
        Clear all the attributes which are not part of the circuit description
        """
        necessary_attrib_names = (
            self.cutoff_names
            + [flux_symbol.name for flux_symbol in self.external_fluxes]
            + [
                offset_charge_symbol.name
                for offset_charge_symbol in self.offset_charges
            ]
            + ["cutoff_names"]
        )
        attrib_keys = list(self.__dict__.keys()).copy()
        for attrib in attrib_keys:
            if attrib[1:] not in necessary_attrib_names:
                if (
                    "cutoff_n_" in attrib
                    or "Φ" in attrib
                    or "cutoff_ext_" in attrib
                    or attrib[1:3] == "ng"
                ):
                    delattr(self, attrib)

    def configure(
        self,
        transformation_matrix: ndarray = None,
        system_hierarchy: list = None,
        subsystem_trunc_dims: list = None,
        closure_branches: List[Branch] = None,
    ):
        """
        Method which re-initializes a circuit instance to update, hierarchical
        diagonalization parameters or closure branches or the variable transformation
        used to describe the circuit.

        Parameters
        ----------
        transformation_matrix:
            A user defined variable transformation which has the dimensions of the
            number nodes (not counting the ground node), by default `None`
        system_hierarchy:
            A list of lists which is provided by the user to define subsystems,
            by default `None`
        subsystem_trunc_dims:
            dict object which can be generated for a specific system_hierarchy using the
            method `truncation_template`, by default `None`
        closure_branches:
            List of branches where external flux variables will be specified, by default
            `None` which then chooses closure branches by an internally generated
            spanning tree. For this option, Circuit should be initialized with `is_flux_dynamic` set to False.

        Raises
        ------
        Exception
            When system_hierarchy is set and subsystem_trunc_dims is not set.
        Exception
            When closure_branches is set and the Circuit instance is initialized with the setting
            `is_flux_dynamic=True`.
        """

        old_system_hierarchy = self.system_hierarchy
        old_subsystem_trunc_dims = self.subsystem_trunc_dims
        if hasattr(self, "symbolic_circuit"):
            old_transformation_matrix = self.transformation_matrix
            old_closure_branches = (
                self.closure_branches
                if not self.symbolic_circuit.is_flux_dynamic
                else None
            )
        try:
            if hasattr(self, "symbolic_circuit"):
                self._configure(
                    transformation_matrix=transformation_matrix,
                    system_hierarchy=system_hierarchy,
                    subsystem_trunc_dims=subsystem_trunc_dims,
                    closure_branches=closure_branches,
                )
            else:
                self._configure_sym_hamiltonian(
                    system_hierarchy=system_hierarchy,
                    subsystem_trunc_dims=subsystem_trunc_dims,
                )
        except:
            # resetting the necessary attributes
            self.system_hierarchy = old_system_hierarchy
            self.subsystem_trunc_dims = old_subsystem_trunc_dims
            if hasattr(self, "symbolic_circuit"):
                self.transformation_matrix = old_transformation_matrix
                self.closure_branches = old_closure_branches
            # Calling configure
            if hasattr(self, "symbolic_circuit"):
                self._configure(
                    transformation_matrix=old_transformation_matrix,
                    system_hierarchy=old_system_hierarchy,
                    subsystem_trunc_dims=old_subsystem_trunc_dims,
                    closure_branches=old_closure_branches,
                )
            else:
                self._configure_sym_hamiltonian(
                    system_hierarchy=old_system_hierarchy,
                    subsystem_trunc_dims=old_subsystem_trunc_dims,
                )
            raise RuntimeError("Configure failed due to incorrect parameters.")

    def _read_symbolic_hamiltonian(
        self, symbolic_hamiltonian: sm.Expr
    ) -> Tuple[List[sm.Expr], List[sm.Expr], Dict[str, List[int]]]:
        free_symbols = symbolic_hamiltonian.free_symbols
        external_fluxes = []
        offset_charges = []
        var_categories = {"periodic": [], "extended": [], "free": [], "frozen": []}
        for var_sym in free_symbols:
            if re.match(r"^ng\d+$", var_sym.name):
                offset_charges.append(var_sym)
            if re.match(r"^Φ\d+$", var_sym.name):
                external_fluxes.append(var_sym)
            if re.match(r"^n\d+$", var_sym.name):
                var_index = get_trailing_number(var_sym.name)
                var_categories["periodic"].append(var_index)
            if re.match(r"^Q\d+$", var_sym.name):
                var_index = get_trailing_number(var_sym.name)
                var_categories["extended"].append(var_index)
        return external_fluxes, offset_charges, var_categories

    def _configure_sym_hamiltonian(
        self, system_hierarchy: list = None, subsystem_trunc_dims: list = None
    ):
        """
        Method which re-initializes a circuit instance to update, hierarchical
        diagonalization parameters or closure branches or the variable transformation
        used to describe the circuit.

        Parameters
        ----------
        system_hierarchy:
            A list of lists which is provided by the user to define subsystems,
            by default `None`
        subsystem_trunc_dims:
            dict object which can be generated for a specific system_hierarchy using the
            method `truncation_template`, by default `None`

        Raises
        ------
        Exception
            when system_hierarchy is set and subsystem_trunc_dims is not set.
        """
        self._frozen = False
        system_hierarchy = system_hierarchy or self.system_hierarchy
        subsystem_trunc_dims = subsystem_trunc_dims or self.subsystem_trunc_dims

        self.hierarchical_diagonalization = (
            True if system_hierarchy is not None else False
        )

        self.is_purely_harmonic = self._is_expression_purely_harmonic(
            self.hamiltonian_symbolic
        )

        (
            self.external_fluxes,
            self.offset_charges,
            self.var_categories,
        ) = self._read_symbolic_hamiltonian(self.hamiltonian_symbolic)

        if self.is_purely_harmonic:
            self.normal_mode_freqs = self.symbolic_circuit.normal_mode_freqs
            if self.ext_basis != "harmonic":
                warnings.warn(
                    "Purely harmonic circuits need ext_basis to be set to 'harmonic'"
                )
                self.ext_basis = "harmonic"

        # initiating the class properties
        if not hasattr(self, "cutoff_names"):
            self.cutoff_names = []
        for var_type in self.var_categories.keys():
            if var_type == "periodic":
                for idx, var_index in enumerate(self.var_categories["periodic"]):
                    if not hasattr(self, f"_cutoff_n_{var_index}"):
                        self._make_property(
                            f"cutoff_n_{var_index}", 5, "update_cutoffs"
                        )
                        self.cutoff_names.append(f"cutoff_n_{var_index}")
            if var_type == "extended":
                for idx, var_index in enumerate(self.var_categories["extended"]):
                    if not hasattr(self, f"_cutoff_ext_{var_index}"):
                        self._make_property(
                            f"cutoff_ext_{var_index}", 30, "update_cutoffs"
                        )
                        self.cutoff_names.append(f"cutoff_ext_{var_index}")

        self.var_index_list = flatten_list(list(self.var_categories.values()))

        # default values for the parameters
        for idx, param in enumerate(self.symbolic_params):
            if not hasattr(self, param.name):
                self._make_property(
                    param.name, self.symbolic_params[param], "update_param_vars"
                )
        # setting the ranges for flux ranges used for discrete phi vars
        for var_index in self.var_categories["extended"]:
            if var_index not in self.discretized_phi_range:
                self.discretized_phi_range[var_index] = (-6 * np.pi, 6 * np.pi)
        # external flux vars
        for flux in self.external_fluxes:
            # setting the default to zero external flux
            if not hasattr(self, flux.name):
                self._make_property(flux.name, 0.0, "update_external_flux_or_charge")
        # offset charges
        for offset_charge in self.offset_charges:
            # default to zero offset charge
            if not hasattr(self, offset_charge.name):
                self._make_property(
                    offset_charge.name, 0.0, "update_external_flux_or_charge"
                )

        # changing the matrix type if necessary
        if (
            len(flatten_list(self.var_categories.values())) == 1
            and self.ext_basis == "harmonic"
        ):
            self.type_of_matrices = "dense"

        self._set_vars()  # setting the attribute vars to store operator symbols

        if system_hierarchy is not None:
            self.hierarchical_diagonalization = (
                system_hierarchy != [] and number_of_lists_in_list(system_hierarchy) > 0
            )

        if not self.hierarchical_diagonalization:
            self.generate_hamiltonian_sym_for_numerics()
            self.operators_by_name = self.set_operators()
        else:
            # list for updating necessary subsystems when calling build hilbertspace
            self.affected_subsystem_indices = []
            self.operators_by_name = None
            self.system_hierarchy = system_hierarchy
            if subsystem_trunc_dims is None:
                raise Exception(
                    "The truncated dimensions attribute for hierarchical "
                    "diagonalization is not set."
                )

            self.subsystem_trunc_dims = subsystem_trunc_dims
            self.generate_hamiltonian_sym_for_numerics()
            self.generate_subsystems()
            self._check_truncation_indices()
            self.operators_by_name = self.set_operators()
            self.affected_subsystem_indices = list(range(len(self.subsystems)))
        # clear unnecessary attribs
        self._clear_unnecessary_attribs()
        self._frozen = True
        self.update()

    def _configure(
        self,
        transformation_matrix: ndarray = None,
        system_hierarchy: list = None,
        subsystem_trunc_dims: list = None,
        closure_branches: List[Branch] = None,
    ):
        """
        Method which re-initializes a circuit instance to update, hierarchical
        diagonalization parameters or closure branches or the variable transformation
        used to describe the circuit.

        Parameters
        ----------
        transformation_matrix:
            A user defined variable transformation which has the dimensions of the
            number nodes (not counting the ground node), by default `None`
        system_hierarchy:
            A list of lists which is provided by the user to define subsystems,
            by default `None`
        subsystem_trunc_dims:
            dict object which can be generated for a specific system_hierarchy using the
            method `truncation_template`, by default `None`
        closure_branches:
            List of branches where external flux variables will be specified, by default
            `None` which then chooses closure branches by an internally generated
            spanning tree.

        Raises
        ------
        Exception
            when system_hierarchy is set and subsystem_trunc_dims is not set.
        """
        self._frozen = False

        system_hierarchy = system_hierarchy or self.system_hierarchy
        subsystem_trunc_dims = subsystem_trunc_dims or self.subsystem_trunc_dims
        closure_branches = closure_branches or self.closure_branches
        if transformation_matrix is None:
            if hasattr(
                self, "transformation_matrix"
            ):  # checking to see if configure is being called outside of init
                transformation_matrix = self.transformation_matrix

        self.hierarchical_diagonalization = (
            True if system_hierarchy is not None else False
        )

        self.symbolic_circuit.configure(
            transformation_matrix=transformation_matrix,
            closure_branches=closure_branches,
        )

        # copying all the required attributes
        required_attributes = [
            "branches",
            "closure_branches",
            "external_fluxes",
            "ground_node",
            "hamiltonian_symbolic",
            "input_string",
            "is_grounded",
            "lagrangian_node_vars",
            "lagrangian_symbolic",
            "nodes",
            "offset_charges",
            "potential_symbolic",
            "potential_node_vars",
            "symbolic_params",
            "transformation_matrix",
            "var_categories",
            "is_purely_harmonic",
        ]
        for attr in required_attributes:
            setattr(self, attr, getattr(self.symbolic_circuit, attr))

        if self.is_purely_harmonic:
            self.normal_mode_freqs = self.symbolic_circuit.normal_mode_freqs
            if self.ext_basis != "harmonic":
                warnings.warn(
                    "Purely harmonic circuits need ext_basis to be set to 'harmonic'"
                )
                self.ext_basis = "harmonic"

        # initiating the class properties
        if not hasattr(self, "cutoff_names"):
            self.cutoff_names = []
        for var_type in self.var_categories.keys():
            if var_type == "periodic":
                for idx, var_index in enumerate(self.var_categories["periodic"]):
                    if not hasattr(self, f"_cutoff_n_{var_index}"):
                        self._make_property(
                            f"cutoff_n_{var_index}", 5, "update_cutoffs"
                        )
                        self.cutoff_names.append(f"cutoff_n_{var_index}")
            if var_type == "extended":
                for idx, var_index in enumerate(self.var_categories["extended"]):
                    if not hasattr(self, f"_cutoff_ext_{var_index}"):
                        self._make_property(
                            f"cutoff_ext_{var_index}", 30, "update_cutoffs"
                        )
                        self.cutoff_names.append(f"cutoff_ext_{var_index}")

        self.var_index_list = flatten_list(list(self.var_categories.values()))

        # default values for the parameters
        for idx, param in enumerate(self.symbolic_params):
            if not hasattr(self, param.name):
                self._make_property(
                    param.name, self.symbolic_params[param], "update_param_vars"
                )
        # setting the ranges for flux ranges used for discrete phi vars
        for var_index in self.var_categories["extended"]:
            if var_index not in self.discretized_phi_range:
                self.discretized_phi_range[var_index] = (-6 * np.pi, 6 * np.pi)
        # external flux vars
        for flux in self.external_fluxes:
            # setting the default to zero external flux
            if not hasattr(self, flux.name):
                self._make_property(flux.name, 0.0, "update_external_flux_or_charge")
        # offset charges
        for offset_charge in self.offset_charges:
            # default to zero offset charge
            if not hasattr(self, offset_charge.name):
                self._make_property(
                    offset_charge.name, 0.0, "update_external_flux_or_charge"
                )

        # changing the matrix type if necessary
        if (
            len(flatten_list(self.var_categories.values())) == 1
            and self.ext_basis == "harmonic"
        ):
            self.type_of_matrices = "dense"

        self._set_vars()  # setting the attribute vars to store operator symbols

        if (len(self.symbolic_circuit.nodes)) > settings.SYM_INVERSION_MAX_NODES:
            self.hamiltonian_symbolic = (
                self.symbolic_circuit.generate_symbolic_hamiltonian(
                    substitute_params=True
                )
            )
        # if the flux is static, remove the linear terms from the potential
        if not self.symbolic_circuit.is_flux_dynamic:
            self.hamiltonian_symbolic = self._shift_harmonic_oscillator_potential(
                self.hamiltonian_symbolic
            )

        if system_hierarchy is not None:
            self.hierarchical_diagonalization = (
                system_hierarchy != [] and number_of_lists_in_list(system_hierarchy) > 0
            )

        if not self.hierarchical_diagonalization:
            self.generate_hamiltonian_sym_for_numerics()
            self.operators_by_name = self.set_operators()
        else:
            # list for updating necessary subsystems when calling build hilbertspace
            self.affected_subsystem_indices = []
            self.operators_by_name = None
            self.system_hierarchy = system_hierarchy
            if subsystem_trunc_dims is None:
                raise Exception(
                    "The truncated dimensions attribute for hierarchical "
                    "diagonalization is not set."
                )

            self.subsystem_trunc_dims = subsystem_trunc_dims
            self.generate_hamiltonian_sym_for_numerics()
            self.generate_subsystems()
            self.update_interactions()
            self._check_truncation_indices()
            self.operators_by_name = self.set_operators()
            self.affected_subsystem_indices = list(range(len(self.subsystems)))
        # clear unnecessary attribs
        self._clear_unnecessary_attribs()
        self._frozen = True
        self.update()

    def supported_noise_channels(self) -> List[str]:
        """Return a list of supported noise channels"""
        # return ['tphi_1_over_f_flux',]
        noise_channels = ["t1_capacitive", "t1_charge_impedance"]
        if len([branch for branch in self.branches if branch.type == "L"]):
            noise_channels.append("t1_inductive")
        if len(self.offset_charges) > 0:
            noise_channels.append("tphi_1_over_f_ng")
        if len(self.external_fluxes) > 0:
            if not self.symbolic_circuit.is_flux_dynamic:
                warnings.warn(
                    "The flag 'is_flux_dynamic' is set to False, so the coherence time estimation due to flux noise might be incorrect. Please set it to True to get the correct results."
                )
            noise_channels.append("tphi_1_over_f_flux")
            noise_channels.append("t1_flux_bias_line")
        if not self.is_purely_harmonic:
            noise_channels.append("tphi_1_over_f_cc")
            # noise_channels.append("t1_quasiparticle_tunneling")
        return noise_channels

    def effective_noise_channels(self):
        supported_channels = self.supported_noise_channels()
        if "t1_charge_impedance" in supported_channels:
            supported_channels.remove("t1_charge_impedance")
        return supported_channels

    def variable_transformation(self) -> None:
        """
        Prints the variable transformation used in this circuit
        """
        trans_mat = self.transformation_matrix
        theta_vars = [
            sm.symbols(f"θ{index}")
            for index in range(
                1, len(self.symbolic_circuit._node_list_without_ground) + 1
            )
        ]
        node_vars = [
            sm.symbols(f"φ{index}")
            for index in range(
                1, len(self.symbolic_circuit._node_list_without_ground) + 1
            )
        ]
        node_var_eqns = []
        for idx, node_var in enumerate(node_vars):
            node_var_eqns.append(
                sm.Eq(node_vars[idx], np.sum(trans_mat[idx, :] * theta_vars))
            )
        if _HAS_IPYTHON:
            self.print_expr_in_latex(node_var_eqns)
        else:
            print(node_var_eqns)

    def sym_lagrangian(
        self,
        vars_type: str = "node",
        print_latex: bool = False,
        return_expr: bool = False,
    ) -> Union[sm.Expr, None]:
        """
        Method that gives a user readable symbolic Lagrangian for the current instance

        Parameters
        ----------
        vars_type:
            "node" or "new", fixes the kind of lagrangian requested, by default "node"
        print_latex:
            if set to True, the expression is additionally printed as LaTeX code
        return_expr:
            if set to True, all printing is suppressed and the function will silently
            return the sympy expression
        """
        if vars_type == "node":
            lagrangian = self.lagrangian_node_vars
            # replace v\theta with \theta_dot
            for var_index in range(
                1, 1 + len(self.symbolic_circuit._node_list_without_ground)
            ):
                lagrangian = lagrangian.replace(
                    sm.symbols(f"vφ{var_index}"),
                    sm.symbols("\\dot{φ_" + str(var_index) + "}"),
                )
            # break down the lagrangian into kinetic and potential part, and rejoin
            # with evaluate=False to force the kinetic terms together and appear first
            sym_lagrangian_PE_node_vars = self.potential_node_vars
            for external_flux in self.external_fluxes:
                sym_lagrangian_PE_node_vars = sym_lagrangian_PE_node_vars.replace(
                    external_flux,
                    sm.symbols(
                        "(2π"
                        + "Φ_{"
                        + str(get_trailing_number(str(external_flux)))
                        + "})"
                    ),
                )
            lagrangian = sm.Add(
                (self._make_expr_human_readable(lagrangian + self.potential_node_vars)),
                (self._make_expr_human_readable(-sym_lagrangian_PE_node_vars)),
                evaluate=False,
            )

        elif vars_type == "new":
            lagrangian = self.lagrangian_symbolic
            # replace v\theta with \theta_dot
            for var_index in self.var_index_list:
                lagrangian = lagrangian.replace(
                    sm.symbols(f"vθ{var_index}"),
                    sm.symbols("\\dot{θ_" + str(var_index) + "}"),
                )
            # break down the lagrangian into kinetic and potential part, and rejoin
            # with evaluate=False to force the kinetic terms together and appear first
            sym_lagrangian_PE_new = self.potential_symbolic.expand()
            for external_flux in self.external_fluxes:
                sym_lagrangian_PE_new = sym_lagrangian_PE_new.replace(
                    external_flux,
                    sm.symbols(
                        "(2π"
                        + "Φ_{"
                        + str(get_trailing_number(str(external_flux)))
                        + "})"
                    ),
                )
            lagrangian = sm.Add(
                (
                    self._make_expr_human_readable(
                        lagrangian + self.potential_symbolic.expand()
                    )
                ),
                (self._make_expr_human_readable(-sym_lagrangian_PE_new)),
                evaluate=False,
            )
        if return_expr:
            return lagrangian
        if print_latex:
            print(latex(lagrangian))
        if _HAS_IPYTHON:
            self.print_expr_in_latex(lagrangian)
        else:
            print(lagrangian)

    def offset_charge_transformation(self) -> None:
        """
        Prints the variable transformation between offset charges of periodic variables
        and the offset node charges
        """
        trans_mat = self.transformation_matrix
        node_offset_charge_vars = [
            sm.symbols(f"q_g{index}")
            for index in range(
                1, len(self.symbolic_circuit._node_list_without_ground) + 1
            )
        ]
        periodic_offset_charge_vars = [
            sm.symbols(f"ng{index}")
            for index in self.symbolic_circuit.var_categories["periodic"]
        ]
        periodic_offset_charge_eqns = []
        for idx, node_var in enumerate(periodic_offset_charge_vars):
            periodic_offset_charge_eqns.append(
                self._make_expr_human_readable(
                    sm.Eq(
                        periodic_offset_charge_vars[idx],
                        np.sum(trans_mat[idx, :] * node_offset_charge_vars),
                    )
                )
            )
        if _HAS_IPYTHON:
            self.print_expr_in_latex(periodic_offset_charge_eqns)
        else:
            print(periodic_offset_charge_eqns)

    def sym_external_fluxes(self) -> Dict[sm.Expr, Tuple["Branch", List["Branch"]]]:
        """
        Method returns a dictionary of Human readable external fluxes with associated
        branches and loops (represented as lists of branches) for the current instance

        Returns
        -------
            A dictionary of Human readable external fluxes with their associated
            branches and loops
        """
        return {
            self._make_expr_human_readable(self.external_fluxes[ibranch]): (
                self.closure_branches[ibranch],
                self.symbolic_circuit._find_loop(self.closure_branches[ibranch]),
            )
            for ibranch in range(len(self.external_fluxes))
        }

    def oscillator_list(self, osc_index_list: List[int]):
        """
        If hierarchical diagonalization is used, specify subsystems that corresponds to
        single-mode oscillators, if there is any. The attributes `_osc_subsys_list` and
        `osc_subsys_list` of the `hilbert_space` attribute of the Circuit instance will
        be assigned accordingly, enabling the correct identification of harmonic modes
        for the dispersive regime analysis in ParameterSweep.

        Parameters
        ----------
        osc_index_list:
            a list of indices of subsystems that are single-mode harmonic oscillators
        """
        # identify if each nominated subsystem indeed have a single harmonic oscillator
        osc_subsys_list = []
        for subsystem_index in osc_index_list:
            subsystem = self.subsystems[subsystem_index]
            if not subsystem.is_purely_harmonic:
                raise Exception(
                    f"the subsystem {subsystem_index} is not purely harmonic"
                )
            elif len(subsystem.var_categories["extended"]) != 1:
                raise Exception(
                    f"the subsystem has more than one harmonic oscillator mode"
                )
            else:
                osc_subsys_list.append(subsystem)
        self.hilbert_space._osc_subsys_list = osc_subsys_list

    def qubit_list(self, qbt_index_list: List[int]):
        """
        If hierarchical diagonalization is used, specify subsystems that corresponds to
        single-mode oscillators, if there is any. The attributes `_osc_subsys_list` and
        `osc_subsys_list` of the `hilbert_space` attribute of the Circuit instance will
        be assigned accordingly, enabling the correct identification of harmonic modes
        for the dispersive regime analysis in ParameterSweep.

        Parameters
        ----------
        qbt_index_list:
            a list of indices of subsystems that are single-mode harmonic oscillators
        """
        # identify if each naminated subsystem indeed have a single harmonic oscillator
        qbt_subsys_list = []
        for subsystem_index in qbt_index_list:
            subsystem = self.subsystems[subsystem_index]
            qbt_subsys_list.append(subsystem)
        self.hilbert_space._qbt_subsys_list = qbt_subsys_list
