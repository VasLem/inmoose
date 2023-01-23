# -----------------------------------------------------------------------------
# Copyright (C) 2013-2022 Michael I. Love, Constantin Ahlmann-Eltze
# Copyright (C) 2023 Maximilien Colange

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
# -----------------------------------------------------------------------------

# This file is based on the file 'R/AllClasses.R' and 'R/methods.R' of the
# Bioconductor DESeq2 package (version 3.16).


import logging
import numpy as np
import pandas as pd
import patsy
from anndata import AnnData
from scipy.stats import median_abs_deviation as mad
from scipy.stats import norm

from ..utils import Factor, rnbinom
from .misc import buildVectorWithNACols, checkFullRank


class MetaDataBase:
    def __init__(self, obj, name):
        self.obj = obj
        self.name = name
        if self.name not in self.obj.attrs:
            self.obj.attrs[self.name] = {}

    def __getitem__(self, index):
        return self.obj.attrs[self.name].get(index)

    def __setitem__(self, index, value):
        self.obj.attrs[self.name][index] = value

    def __delitem__(self, index):
        del self.obj.attrs[self.name][index]

    def filter(self, items=None, like=None, regex=None):
        import re

        if len([x for x in [items, like, regex] if x is not None]) != 1:
            raise ValueError("pass exactly one argument to filter")
        if items is not None:
            cols = [k for k, v in self.obj.attrs[self.name].items() if v in items]
        if like is not None:
            cols = [k for k, v in self.obj.attrs[self.name].items() if like in v]
        if regex is not None:
            cols = [
                k for k, v in self.obj.attrs[self.name].items() if re.search(regex, v)
            ]

        return self.obj.filter(cols)


@pd.api.extensions.register_dataframe_accessor("type")
class TypeMetaData(MetaDataBase):
    def __init__(self, obj):
        super().__init__(obj, "type")


@pd.api.extensions.register_dataframe_accessor("description")
class DescMetaData(MetaDataBase):
    def __init__(self, obj):
        super().__init__(obj, "description")


class DispFunction:
    def __init__(self, f, dispPriorVar=None, varLogDispEsts=None):
        self.f = f
        self.dispPriorVar = dispPriorVar
        self.varLogDispEsts = varLogDispEsts

    def __call__(self, *args, **kwargs):
        return self.f(*args, **kwargs)


class DESeqDataSet(AnnData):
    """
    AnnData stores observations (samples) of variables/features in the rows of a matrix.

    Attributes
    ----------
    modelMatrix : patsy.DesignMatrix
        the design matrix
    """

    from .dispersions import estimateDispersions_dds as estimateDispersions
    from .estimateSizeFactors import estimateSizeFactors_dds as estimateSizeFactors
    from .results import results_dds as results

    def __init__(self, countData, clinicalData=None, design=None, ignoreRank=False):
        """
        Arguments
        ---------
        countData : pandas.DataFrame
            Raw counts. One column per gene, one row per sample.
        clinicalData : pandas.DataFrame

        """

        if isinstance(countData, AnnData):
            if any((clinicalData,)):
                raise ValueError(
                    "If `countData` is an AnnData, no further arguments are needed"
                )
        super().__init__(X=countData, obs=clinicalData, dtype=int)

        if design is not None:
            self.design = design
            if not ignoreRank:
                checkFullRank(self.design)

        if isinstance(countData, DESeqDataSet):
            for k, v in countData.__dict__.items():
                if k not in self.__dict__:
                    self.__dict__[k] = v
        else:
            self.modelMatrix = None
            self.modelMatrixType = None
            self.weightsOK = None

    def copy(self):
        res = __class__(super().copy())
        res.design = self.design
        for k, v in self.__dict__.items():
            if k not in res.__dict__:
                res.__dict__[k] = v
        return res

    @property
    def design(self):
        return self.obsm["design"]

    @design.setter
    def design(self, d):
        # if d is already a design matrix, then this is a no-op
        # if design is already a matrix, then it is normalized (if needed) and other metadata specific to a design matrix are added. The `data=self.obs` part is ignored.
        self.obsm["design"] = patsy.dmatrix(d, data=self.obs, NA_action="raise")

    @property
    def sizeFactors(self):
        try:
            return self.obs["sizeFactors"]
        except KeyError:
            return None

    @sizeFactors.setter
    def sizeFactors(self, sf):
        if not np.all(~np.isnan(sf)):
            raise ValueError("size factors should not be nan")
        if not np.all(np.isfinite(sf)):
            raise ValueError("size factors should be finite")
        if not np.all(np.greater(sf, 0)):
            raise ValueError("size factors should be positive")
        self.obs["sizeFactors"] = sf

    @sizeFactors.deleter
    def sizeFactors(self):
        del self.obs["sizeFactors"]

    @property
    def normalizationFactors(self):
        try:
            return self.layers["normalizationFactors"]
        except KeyError:
            return None

    @normalizationFactors.setter
    def normalizationFactors(self, nf):
        if not np.all(~np.isnan(nf)):
            raise ValueError("normalization factors should not be nan")
        if not np.all(np.isfinite(nf)):
            raise ValueError("normalization factors should be finite")
        if not np.all(np.greater(nf, 0)):
            raise ValueError("normalization factors should be positive")
        self.layers["normalizationFactors"] = nf

    @normalizationFactors.deleter
    def normalizationFactors(self):
        del self.layers["normalizationFactors"]

    @property
    def dispersionFunction(self):
        return DispFunction(
            self._dispersionFunction, self._dispPriorVar, self._varLogDispEsts
        )

    @dispersionFunction.setter
    def dispersionFunction(self, v):
        raise RuntimeError(
            "do not write dispersionFunction, use setDispFunction method"
        )

    def setDispFunction(self, value, estimateVar=True):
        if not isinstance(value, DispFunction):
            value = DispFunction(value)

        # the following will add 'dispFit' to self.var
        # first check to see that we have 'baseMean' and 'allZero'
        if "baseMean" not in self.var or "allZero" not in self.var:
            self = self.getBaseMeansAndVariances()
        # warning about existing 'dispFit' data will be removed
        if "dispFit" in self.var:
            del self.var["dispFit"]
        # now call the dispersionFunction on 'baseMean' to make 'dispFit'
        nonzeroIdx = ~self.var["allZero"]
        dispFit = value(self.var["baseMean"][nonzeroIdx])
        self.var["dispFit"] = buildVectorWithNACols(dispFit, self.var["allZero"])
        self.var.type["dispFit"] = "intermediate"
        self.var.description["dispFit"] = "fitted values of dispersion"

        # estimate variance of log dispersion around the fit
        if estimateVar:
            # need to estimate variance of log dispersion residuals
            minDisp = 1e-8
            dispGeneEst = self.var["dispGeneEst"][nonzeroIdx]
            aboveMinDisp = dispGeneEst >= minDisp * 100
            if np.nansum(aboveMinDisp) > 0:
                dispResiduals = np.log(dispGeneEst) - np.log(dispFit)
                varLogDispEsts = (
                    mad(dispResiduals[aboveMinDisp], nan_policy="omit") ** 2
                )
                value.varLogDispEsts = varLogDispEsts
            else:
                logging.info(
                    "variance of dispersion residuals not estimated (necessary only for differential expression calling)"
                )

        # store the dispersion function
        self._dispersionFunction = value.f
        self._dispPriorVar = value.dispPriorVar
        self._varLogDispEsts = value.varLogDispEsts
        return self

    def __getitem__(self, index):
        res = self.__class__(super().__getitem__(index).copy())
        # make sure the design is valid
        res.design = self.design.design_info
        # set the attributes already set in __init__
        res.modelMatrix = self.modelMatrix
        res.modelMatrixType = self.modelMatrixType
        res.weightsOK = self.weightsOK
        # other attributes
        for k, v in self.__dict__.items():
            if k not in res.__dict__:
                res.__dict__[k] = v
        # preserve metadata
        for c in self.var.columns:
            t = self.var.type[c]
            if t is not None:
                res.var.type[c] = t
            d = self.var.description[c]
            if d is not None:
                res.var.description[c] = d
        return res

    def counts(self, normalized=False, replaced=False):
        if replaced:
            if "replaceCounts" in self.layers:
                cnts = self.layers["replaceCounts"]
            else:
                logging.warnings.warn(
                    "there is no layer named 'replacedCounts', using original. calling DESeq() will replace outliers if they are detected and store this layers."
                )
                cnts = self.X
        else:
            cnts = self.X

        if not normalized:
            return cnts
        else:
            if self.normalizationFactors is not None:
                return cnts / self.normalizationFactors
            elif self.sizeFactors is None or np.isnan(self.sizeFactors).any():
                raise ValueError(
                    "first calculate size factors, add normalizationFactors, or set normalized=False"
                )
            else:
                return cnts / self.sizeFactors.values[:, None]

    def designAndArgChecker(self, betaPrior):
        """
        Arguments
        ---------
        betaPrior : bool
        """
        di = self.design.design_info
        termsOrder = np.array([len(t.factors) for t in di.terms])
        hasIntercept = 0 in termsOrder
        interactionPresent = (termsOrder > 1).any()

        if betaPrior and not hasIntercept:
            raise ValueError(
                "betaPrior=True can only be used if the design has an intercept. If not, use betaPrior=False"
            )
        if betaPrior and interactionPresent:
            raise ValueError(
                "betaPrior=False should be used for designs with interactions"
            )

        if not betaPrior:
            if np.linalg.matrix_rank(self.design) < self.design.shape[1]:
                raise ValueError("full model matrix is not full rank")

    def getBaseMeansAndVariances(self):
        """Get base means and variances

        An internally used function to calculate the gene (columns) means
        and variances from the normalized counts, which requires that
        estimateSizeFactors has already been called. Adds these and a Boolean
        var to identify the columns whose sum is zero.
        """
        cts_norm = self.counts(normalized=True)
        if "weights" in self.layers:
            wts = self.layers["weights"]
            cts_norm = wts * cts_norm
        self.var["baseMean"] = np.mean(cts_norm, 0)
        self.var.type["baseMean"] = "intermediate"
        self.var.description["baseMean"] = "mean of normalized counts for all samples"
        self.var["baseVar"] = np.var(cts_norm, 0, ddof=1)
        self.var.type["baseVar"] = "intermediate"
        self.var.description[
            "baseVar"
        ] = "variance of normalized counts for all samples"
        self.var["allZero"] = np.sum(self.counts(), 0) == 0
        self.var.type["allZero"] = "intermediate"
        self.var.description["allZero"] = "all counts for a gene are zero"

        return self

    def getSizeOrNormFactors(self):
        """simple function to return a matrix of size factors or normalization factors"""
        if self.normalizationFactors is not None:
            return self.normalizationFactors
        else:
            return self.sizeFactors.to_numpy()[:, None].repeat(self.n_vars, axis=1)

    def resultsNames(self):
        return self.var.description.filter(regex="log2 fold change").columns

    def removeResults(self):
        self.var = self.var.drop(self.var.type.filter("results").columns, axis=1)
        return self

    def makeExpandedModelMatrix(self):
        data = self.obs.apply(
            lambda col: Factor(col)
            .add_categories(["__null__"])
            .reorder_categories(col.dtype.categories.insert(0, "__null__"))
            if isinstance(col.dtype, pd.CategoricalDtype)
            else col
        )
        # formula = "+".join([f"C({t.name()}, Treatment(reference='__null__'))"
        formula = "+".join(
            [
                f"{t.name()}" if len(t.factors) != 0 else "1"
                for t in self.design.design_info.terms
            ]
        )
        return patsy.dmatrix(formula, data=data)

    def getDesignFactors(self):
        return [
            f.name()
            for f, info in self.design.design_info.factor_infos.items()
            if info.type == "categorical"
        ]

    def addAllContrasts(self, betaMatrix):
        """add all first order contrasts"""
        designFactors = self.getDesignFactors()
        coldata = self.obs
        for f in designFactors:
            lvls = coldata[f].dtype.categories
            mmColnames = [f"{f}[T.{c}]" for c in lvls]
            M = betaMatrix.filter(mmColnames)
            n = M.shape[1]
            if n > 1:
                ii = [f"{c}" for k in range(1, n) for c in M.columns[k:]]
                jj = [f"{c}" for k, c in enumerate(M.columns) for _ in range(n - k - 1)]
                contrastCols = pd.DataFrame(
                    {
                        f"{f}Cntrst{k}": M[i] - M[j]
                        for k, (i, j) in enumerate(zip(ii, jj))
                    }
                )
                betaMatrix = pd.concat([betaMatrix, contrastCols], axis=1)
        return betaMatrix

    def averagePriorsOverLevels(self, betaPriorVar):
        expandedModelMatrix = self.makeExpandedModelMatrix()
        expandedNames = expandedModelMatrix.design_info.column_names
        betaPriorIn = betaPriorVar
        betaPriorOut = pd.Series(np.zeros(len(expandedNames)), index=expandedNames)
        commonIndex = [n for n in expandedNames if n in betaPriorIn.columns]
        betaPriorOut[commonIndex] = betaPriorIn[commonIndex].values.squeeze()
        designFactors = self.getDesignFactors()
        for f in designFactors:
            lvls = self.obs[f].dtype.categories
            mmColnames = pd.Index([f"{f}[T.{c}]" for c in lvls]).append(
                betaPriorIn.filter(regex=f"^{f}Cntrst\d+$").index
            )
            meanPriorVar = np.mean(betaPriorIn.filter(mmColnames).values)
            betaPriorOut[np.isin(betaPriorOut.index, mmColnames)] = meanPriorVar

        if np.any(np.isnan(betaPriorOut)):
            raise ValueError("beta prior is NA for some cols")
        if not np.all(betaPriorOut > 0):
            raise ValueError("beta prior is <= 0 for some cols")

        return betaPriorOut


def makeExampleDESeqDataSet(
    n=1000,
    m=12,
    betaSD=0,
    interceptMean=4,
    interceptSD=2,
    dispMeanRel=lambda x: 4 / x + 1,
    sizeFactors=None,
    seed=None,
):
    """
    Arguments
    ---------
    n : int
        the number of genes
    m : int
        the number of samples
    betaSD : float
        the dispersion standard deviation
        optional, defaults to 0
    """
    if sizeFactors is None:
        sizeFactors = np.ones(m)
    sizeFactors = np.asarray(sizeFactors)

    rng = np.random.default_rng(seed)
    beta = np.column_stack(
        [
            norm(loc=interceptMean, scale=interceptSD).rvs(n, random_state=rng),
            norm(loc=0, scale=betaSD).rvs(n, random_state=rng),
        ]
    )
    dispersion = dispMeanRel(2 ** (beta[:, 0]))
    clinData = pd.DataFrame(
        {
            "condition": Factor(
                np.concatenate(
                    [
                        np.full(int(np.ceil(m / 2)), "A"),
                        np.full(int(np.floor(m / 2)), "B"),
                    ]
                )
            )
        }
    )
    clinData.index = [f"sample{i}" for i in range(m)]

    if m > 1:
        x = patsy.dmatrix("~clinData['condition']")
    else:
        x = np.column_stack([np.ones(m, dtype=int), np.zeros(m, dtype=int)])

    mu = 2.0 ** (x @ beta.T) * sizeFactors.reshape(x.shape[0], 1)
    countData = rnbinom((m, n), mu=mu, size=1 / dispersion, seed=rng)
    countData = pd.DataFrame(countData, index=[f"sample{i}" for i in range(m)])

    if m > 1:
        design = "~condition"
    else:
        design = "~1"

    obj = DESeqDataSet(countData=countData, clinicalData=clinData, design=design)
    obj.var["trueIntercept"] = beta[:, 0]
    obj.var.type["trueIntercept"] = "input"
    obj.var.description["trueIntercept"] = "simulated intercept values"
    obj.var["trueBeta"] = beta[:, 1]
    obj.var.type["trueBeta"] = "input"
    obj.var.description["trueBeta"] = "simulated beta values"
    obj.var["trueDisp"] = dispersion
    obj.var.type["trueDisp"] = "input"
    obj.var.description["trueDisp"] = "simulated dispersion values"

    return obj
