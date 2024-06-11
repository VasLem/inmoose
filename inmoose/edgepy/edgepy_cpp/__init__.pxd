# distutils: language = c++
#-----------------------------------------------------------------------------
# Copyright (C) 2022-2023 Maximilien Colange

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#-----------------------------------------------------------------------------

from libcpp cimport bool, pair, vector
from numpy cimport ndarray

# cf. file src/utils.h from edgeR source repo

cdef public ndarray[double, ndim=1] vector2ndarray "vector2ndarray"(const vector.vector[double]& data)
cdef public double compute_unit_nb_deviance(double, double, double)


cdef extern from "maximize_interpolant.cpp":
    cpdef vector.vector[double] cxx_maximize_interpolant "maximize_interpolant"(vector.vector[double] spts, ndarray[double] likelihoods) except +

