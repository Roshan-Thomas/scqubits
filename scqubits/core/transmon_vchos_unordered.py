import math

import numpy as np
import scipy as sp
import itertools
import scipy.constants as const
from scipy.special import hermite
from scipy.linalg import LinAlgError

import scqubits.core.constants as constants
import scqubits.utils.plot_defaults as defaults
import scqubits.utils.plotting as plot
from scqubits.core.discretization import Grid1d
from scqubits.core.qubit_base import QubitBaseClass1d
from scqubits.core.storage import WaveFunction
from scqubits.utils.spectrum_utils import standardize_phases, order_eigensystem


#-Flux Qubit using VCHOS 

class TransmonVCHOSUnordered(QubitBaseClass1d):
    def __init__(self, EJ, EC, ng, kmax, num_exc):
        self.EJ = EJ
        self.EC = EC
        self.ng = ng
        self.kmax = kmax
        self.num_exc = num_exc
        
        self._sys_type = 'transmon_vchos_unordered'
        self._evec_dtype = np.complex_
        self._default_grid = Grid1d(-6.5*np.pi, 6.5*np.pi, 651)
                
    def potential(self, phi):
        """Transmon phase-basis potential evaluated at `phi`.

        Parameters
        ----------
        phi: float
            phase variable value

        Returns
        -------
        float
        """
        return -self.EJ * np.cos(phi)
    
    def kineticmat(self):
        Xi = (8.0*self.EC/self.EJ)**(1/4)
        a = self.a_operator()
        klist = itertools.product(np.arange(-self.kmax, self.kmax + 1), repeat=1)
        jkvals = next(klist,-1)
        kinetic_mat = np.zeros((self.num_exc+1, self.num_exc+1), dtype=np.complex128)
        while jkvals != -1:
            phik = 2.0*np.pi*jkvals[0]
            
            translation_op = sp.linalg.expm((Xi**(-1)*phik/np.sqrt(2.))*(a - a.T))
            n = -(1j*Xi**(-1)/np.sqrt(2.))*(a - a.T)
            
            kin = (4.0*self.EC*np.exp(-1j*self.ng*phik)
                   *np.matmul(n, np.matmul(n, translation_op)))
            
            kinetic_mat += kin
            
            jkvals = next(klist, -1)
        return kinetic_mat
    
    def potentialmat(self):
        Xi = (8.0*self.EC/self.EJ)**(1/4)
        a = self.a_operator()
        klist = itertools.product(np.arange(-self.kmax, self.kmax + 1), repeat=1)
        jkvals = next(klist,-1)
        potential_mat = np.zeros((self.num_exc+1, self.num_exc+1), dtype=np.complex128)
        while jkvals != -1:
            phik = 2.0*np.pi*jkvals[0]
            
            translation_op = sp.linalg.expm((Xi**(-1)*phik/np.sqrt(2.))*(a - a.T))
            
            pot_op = sp.linalg.expm((1j/np.sqrt(2.))*Xi*(a + a.T))
            pot = -0.5*self.EJ*(pot_op + pot_op.conjugate().T)
            
            pot = np.exp(-1j*self.ng*phik)*np.matmul(pot, translation_op)
            potential_mat += pot
            
            jkvals = next(klist, -1)
        return potential_mat
    
    def inner_product(self):
        Xi = (8.0*self.EC/self.EJ)**(1/4)
        a = self.a_operator()
        inner_mat = np.zeros((self.num_exc+1, self.num_exc+1), dtype=np.complex128)
        klist = itertools.product(np.arange(-self.kmax, self.kmax + 1), repeat=1)
        jkvals = next(klist,-1)
        while jkvals != -1:
            phik = 2.0*np.pi*jkvals[0]
            
            V_op = self.V_operator(-phik)
            V_op_dag = self.V_operator(phik).T
            
            inner = np.exp(-1j*self.ng*phik)*np.matmul(V_op_dag, V_op)
            inner_mat += inner
            
            jkvals = next(klist, -1)
        return inner_mat

    def inner_product_unordered_old(self):
        Xi = (8.0*self.EC/self.EJ)**(1/4)
        a = self.a_operator()
        inner_mat = np.zeros((self.num_exc+1, self.num_exc+1), dtype=np.complex128)
        klist = itertools.product(np.arange(-self.kmax, self.kmax + 1), repeat=1)
        jkvals = next(klist,-1)
        while jkvals != -1:
            phik = 2.0*np.pi*jkvals[0]
            
            translation_op = sp.linalg.expm((Xi**(-1)*phik/np.sqrt(2.))*(a - a.T))
            
            inner = np.exp(-1j*self.ng*phik)*translation_op
            inner_mat += inner
            
            jkvals = next(klist, -1)
        return inner_mat
    
    def a_operator(self):
        """Return the lowering operator"""
        a = np.array([np.sqrt(num) for num in range(1, self.num_exc + 1)])
        a_mat = np.diag(a,k=1)
        return a_mat
    
    def _identity(self):
        return np.identity(self.num_exc+1)
                                
    def V_operator(self, phi):
        """Return the V operator """
        Xi = (8.0*self.EC/self.EJ)**(1/4)
        prefactor = np.exp(-.125 * (phi*Xi**(-1))**2)
        op = sp.linalg.expm((phi*Xi**(-1)/np.sqrt(2.))
                            *self.a_operator())
        return prefactor * op                                               
                                                                          
    def hamiltonian(self):
        """Construct the Hamiltonian"""
        return (self.kineticmat() + self.potentialmat())
    
    def _evals_calc(self, evals_count):
        hamiltonian_mat = self.hamiltonian()
        inner_product_mat = self.inner_product()
        try:
            evals = sp.linalg.eigh(hamiltonian_mat, b=inner_product_mat, 
                                   eigvals_only=True, eigvals=(0, evals_count - 1))
        except LinAlgError:
            print("exception")
#            global_min = self.sorted_minima()[0]
#            global_min_value = self.potential(global_min)
#            hamiltonian_mat += -global_min_value*inner_product_mat
            evals = sp.sparse.linalg.eigsh(hamiltonian_mat, k=evals_count, M=inner_product_mat, 
                                           sigma=0.00001, return_eigenvectors=False)
        return np.sort(evals)

    def _esys_calc(self, evals_count):
        hamiltonian_mat = self.hamiltonian()
        inner_product_mat = self.inner_product()
        try:
            evals, evecs = sp.linalg.eigh(hamiltonian_mat, b=inner_product_mat,
                                          eigvals_only=False, eigvals=(0, evals_count - 1))
            evals, evecs = order_eigensystem(evals, evecs)
        except LinAlgError:
            print("exception")
#            global_min = self.sorted_minima()[0]
#            global_min_value = self.potential(global_min)
#            hamiltonian_mat += -global_min_value*inner_product_mat
            evals, evecs = sp.sparse.linalg.eigsh(hamiltonian_mat, k=evals_count, M=inner_product_mat, 
                                                  sigma=0.00001, return_eigenvectors=True)
            evals, evecs = order_eigensystem(evals, evecs)
        return evals, evecs
    
    def harm_osc_wavefunction(self, n, x):
        """For given quantum number n=0,1,2,... return the value of the harmonic oscillator wave function
        :math:`\\psi_n(x) = N H_n(x) \\exp(-x^2/2)`, N being the proper normalization factor. It is assumed
        that the harmonic length has already been accounted for. Therefore that portion of the normalization
        factor must be accounted for outside the function.

        Parameters
        ----------
        n: int
            index of wave function, n=0 is ground state
        x: float or ndarray
            coordinate(s) where wave function is evaluated

        Returns
        -------
        float or ndarray
            value(s) of harmonic oscillator wave function
        """
        return ((2.0 ** n * sp.special.gamma(n + 1.0)) ** (-0.5) * np.pi ** (-0.25) 
                * sp.special.eval_hermite(n, x) 
                * np.exp(-x**2/2.))
 