import unittest
import numpy as np

from inmoose.utils import Factor
from inmoose.deseq2 import DESeq, makeExampleDESeqDataSet


class Test(unittest.TestCase):
    def test_results(self):
        """test that results work as expected and throw errors"""
        ## test contrasts
        dds = makeExampleDESeqDataSet(n=200, m=12)
        dds.obs["condition"] = Factor(np.repeat([1, 2, 3], 4))
        dds.obs["group"] = Factor(np.repeat([[1, 2]], 6, axis=0).flatten())
        dds.obs["foo"] = np.repeat(["lo", "hi"], 6)
        dds.counts()[:, 0] = np.repeat([100, 200, 800], 4)

        dds.design = "~ group + condition"

        # calling results too early
        with self.assertRaisesRegexp(
            ValueError,
            expected_regex="could not find results in obj. first run DESeq()",
        ):
            dds.results()

        dds.sizeFactors = np.ones(dds.n_obs)
        dds = DESeq(dds)
        res = dds.results()
        # TODO
        # show_res = res.show()
        # summary_res = res.summary()

        # various results error checking
        with self.assertRaisesRegex(
            ValueError,
            expected_regex="the LRT requires the user to run nbinomLRT or DESeq",
        ):
            dds.results(test="LRT")
        with self.assertRaisesRegex(
            ValueError,
            expected_regex="when testing altHypothesis='lessAbs', set the argument lfcThreshold to a positive value",
        ):
            dds.results(altHypothesis="lessAbs")
        with self.assertRaisesRegex(
            ValueError, expected_regex="'name' should be a string"
        ):
            dds.results(name=["Intercept", "group1"])
        with self.assertRaisesRegex(ValueError, expected_regex="foo is not a factor"):
            dds.results(contrast=["foo", "B", "A"])
        with self.assertRaisesRegex(
            ValueError,
            expected_regex="as 1 is the reference level, was expecting condition_4_vs_1 to be present in",
        ):
            dds.results(contrast=["condition", "4", "1"])
        with self.assertRaisesRegex(
            ValueError, expected_regex="invalid value for test: foo"
        ):
            dds.results(test="foo")
        with self.assertRaisesRegex(
            ValueError,
            expected_regex="numeric contrast vector should have one element for every element of",
        ):
            dds.results(contrast=False)
        with self.assertRaisesRegex(
            ValueError,
            expected_regex="'contrast', as a pair of lists, should have length 2",
        ):
            dds.results(contrast=["a", "b", "c", "d"])
        with self.assertRaisesRegex(
            ValueError, expected_regex="1 and 1 should be different level names"
        ):
            dds.results(contrast=["condition", "1", "1"])

        dds.results(independentFiltering=False)
        dds.results(contrast=["condition_2_vs_1"])

        with self.assertRaisesRegex(
            ValueError,
            expected_regex="condition_3_vs_1 and condition_3_vs_1 should be different level names",
        ):
            dds.results(
                contrast=["condition_2_vs_1", "condition_3_vs_1", "condition_3_vs_1"]
            )
        with self.assertRaisesRegex(
            ValueError,
            expected_regex="'contrast', as a pair of lists, should have lists of strings as elements",
        ):
            dds.results(contrast=["condition_2_vs_1", 1])
        with self.assertRaisesRegex(
            ValueError,
            expected_regex="all elements of the 2-element contrast should be elements of",
        ):
            dds.results(contrast=["condition_2_vs_1", "foo"])
        with self.assertRaisesRegex(
            ValueError,
            expected_regex="elements in the 2-element contrast should only appear in the numerator",
        ):
            dds.results(contrast=["condition_2_vs_1", "condition_2_vs_1"])
        with self.assertRaisesRegex(
            ValueError,
            expected_regex="all elements of the 2-element contrast should be elements of",
        ):
            dds.results(contrast=["", ""])
        with self.assertRaisesRegex(
            ValueError,
            expected_regex="numeric contrast vector should have one element for every element of",
        ):
            dds.results(contrast=np.repeat(0, 6))
        with self.assertRaisesRegex(ValueError, expected_regex="foo is not a factor"):
            dds.results(contrast=["foo", "lo", "hi"])

        self.assertAlmostEqual(
            dds.results(contrast=["condition", "1", "3"]).log2FoldChange[0],
            -3,
            delta=1e-6,
        )
        self.assertAlmostEqual(
            dds.results(contrast=["condition", "1", "2"]).log2FoldChange[0],
            -1,
            delta=1e-6,
        )
        self.assertAlmostEqual(
            dds.results(contrast=["condition", "2", "3"]).log2FoldChange[0],
            -2,
            delta=1e-6,
        )

        # test a number of contrast as list options
        self.assertAlmostEqual(
            dds.results(
                contrast=["condition_3_vs_1", "condition_2_vs_1"]
            ).log2FoldChange[0],
            2,
            delta=1e-6,
        )
        dds.results(
            contrast=["condition_3_vs_1", "condition_2_vs_1"], listValues=[0.5, -0.5]
        )
        dds.results(contrast=["condition_3_vs_1", []])
        dds.results(contrast=["condition_3_vs_1", []], listValues=[0.5, -0.5])
        dds.results(contrast=[[], "condition_2_vs_1"])
        dds.results(contrast=[[], "condition_2_vs_1"], listValues=[0.5, -0.5])

        # test no prior on intercept
        self.assertTrue(np.array_equal(dds.betaPriorVar, np.repeat(1e6, 4)))

        # test thresholding
        dds.results(lfcThreshold=np.log2(1.5))
        dds.results(lfcThreshold=1, altHypothesis="lessAbs")
        dds.results(lfcThreshold=1, altHypothesis="greater")
        dds.results(lfcThreshold=1, altHypothesis="less")

        dds3 = DESeq(dds, betaPrior=True)
        with self.assertRaisesRegex(
            ValueError,
            expected_regex="testing altHypothesis='lessAbs' requires setting the DESeq\(\) argument betaPrior=False",
        ):
            dds3.results(lfcThreshold=1, altHypothesis="lessAbs")

    def test_results_zero_intercept(self):
        """test results on designs with zero intercept"""
        dds = makeExampleDESeqDataSet(n=100, m=12, seed=42)
        dds.obs["condition"] = Factor(np.repeat([1, 2, 3], 4))
        dds.obs["group"] = Factor(np.repeat([[1, 2]], 6, axis=0).flatten())

        dds.X[:, 0] = np.repeat([100, 200, 400], 4)

        dds.design = "~ 0 + condition"
        dds = DESeq(dds, betaPrior=False)

        self.assertAlmostEqual(dds.results().log2FoldChange[0], 2, delta=0.1)
        self.assertAlmostEqual(
            dds.results(contrast=["condition", "2", "1"]).log2FoldChange[0],
            1.25,
            delta=0.1,
        )
        self.assertAlmostEqual(
            dds.results(contrast=["condition", "3", "2"]).log2FoldChange[0],
            0.68,
            delta=0.1,
        )
        self.assertAlmostEqual(
            dds.results(contrast=["condition", "1", "3"]).log2FoldChange[0],
            -2,
            delta=0.1,
        )
        self.assertAlmostEqual(
            dds.results(contrast=["condition", "1", "2"]).log2FoldChange[0],
            -1.25,
            delta=0.1,
        )
        self.assertAlmostEqual(
            dds.results(contrast=["condition", "2", "3"]).log2FoldChange[0],
            -0.68,
            delta=0.1,
        )
        with self.assertRaisesRegex(
            ValueError,
            expected_regex="condition\[4\] and condition\[1\] are expected to be in",
        ):
            dds.results(contrast=["condition", "4", "1"])

        dds.design = "~ 0 + group + condition"
        dds = DESeq(dds, betaPrior=False)

        self.assertAlmostEqual(dds.results().log2FoldChange[0], 2, delta=0.1)
        self.assertAlmostEqual(
            dds.results(contrast=["condition", "3", "1"]).log2FoldChange[0],
            2,
            delta=0.1,
        )
        self.assertAlmostEqual(
            dds.results(contrast=["condition", "2", "1"]).log2FoldChange[0],
            1.25,
            delta=0.1,
        )
        self.assertAlmostEqual(
            dds.results(contrast=["condition", "3", "2"]).log2FoldChange[0],
            0.68,
            delta=0.1,
        )
        self.assertAlmostEqual(
            dds.results(contrast=["condition", "1", "3"]).log2FoldChange[0],
            -2,
            delta=0.1,
        )
        self.assertAlmostEqual(
            dds.results(contrast=["condition", "1", "2"]).log2FoldChange[0],
            -1.25,
            delta=0.1,
        )
        self.assertAlmostEqual(
            dds.results(contrast=["condition", "2", "3"]).log2FoldChange[0],
            -0.68,
            delta=0.1,
        )

    @unittest.skip("LRT is not implemented yet")
    def test_results_likelihood_ratio_test(self):
        """test results with likelihood ratio test"""
        dds = makeExampleDESeqDataSet(n=100)
        dds.obs["group"] = Factor([1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2])
        dds.design = "~ group + condition"
        dds = DESeq(dds, test="LRT", reduced="~group")

        self.assertFalse(
            np.all(
                dds.results(name="condition_B_vs_A").stat
                == dds.results(name="condition_B_vs_A", test="Wald").stat
            )
        )

        # LFC are already MLE
        with self.assertRaisesRegex(
            ValueError,
            expected_regex="addMLE=TRUE is only for when a beta prior was used",
        ):
            dds.results(addMLE=True)
        with self.assertRaisesRegex(
            ValueError,
            expected_regex="tests of log fold change above or below a theshold must be Wald tests",
        ):
            dds.results(lfcThreshold=1, test="LRT")

        self.assertTrue(
            np.all(
                dds.results(test="LRT", contrast=["group", "1", "2"]).log2FoldChange
                == -dds.results(test="LRT", contrast=["group", "2", "1"]).log2FoldChange
            )
        )

    @unittest.skip("not sure what to test")
    def test_results_basics(self):
        """test that results basics regarding format, saveCols, tidy, MLE, remove are working"""
        dds = makeExampleDESeqDataSet(n=100)
        dds.var["score"] = np.arange(1, 101)
        dds = DESeq(dds)

        raise NotImplementedError()

    @unittest.skip("not sure what to test")
    def test_results_custom_filters(self):
        """test that custom filters can be provided to results()"""
        dds = makeExampleDESeqDataSet(n=200, m=4, betaSD=np.repeat([0, 2], [150, 50]))
        dds = DESeq(dds)
        res = dds.results()
        method = "BH"
        alpha = 0.1

        raise NotImplementedError()
