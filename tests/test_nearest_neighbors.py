import unittest
from unittest.mock import patch, MagicMock

import numpy as np
import scipy.sparse as sp
from scipy.spatial.distance import pdist, cdist, squareform
import pynndescent
import hnswlib
from sklearn import datasets

from numba import njit
from numba.core.registry import CPUDispatcher
from sklearn.utils import check_random_state

from openTSNE import nearest_neighbors
from .test_tsne import check_mock_called_with_kwargs


class KNNIndexTestMixin:
    knn_index = NotImplemented

    def __init__(self, *args, **kwargs):
        self.x1 = np.random.normal(100, 50, (150, 50))
        self.x2 = np.random.normal(100, 50, (100, 50))
        self.iris = datasets.load_iris().data
        super().__init__(*args, **kwargs)

    def test_returns_correct_number_neighbors_query_train(self):
        ks = [1, 5, 10, 30, 50]
        n_samples = self.x1.shape[0]
        index: nearest_neighbors.KNNIndex = self.knn_index("euclidean")

        for k in ks:
            indices, distances = index.build(self.x1, k=k)
            self.assertEqual(indices.shape, (n_samples, k))
            self.assertEqual(distances.shape, (n_samples, k))

    def test_returns_proper_distances_query_train(self):
        index: nearest_neighbors.KNNIndex = self.knn_index("euclidean")
        indices, distances = index.build(self.iris, k=30)
        self.assertTrue(np.isfinite(distances).all())

    def test_returns_correct_number_neighbors_query(self):
        ks = [1, 5, 10, 30, 50]
        n_samples = self.x2.shape[0]
        index: nearest_neighbors.KNNIndex = self.knn_index("euclidean")
        index.build(self.x1, k=30)

        for k in ks:
            indices, distances = index.query(self.x2, k)
            self.assertEqual(indices.shape, (n_samples, k))
            self.assertEqual(distances.shape, (n_samples, k))

    def test_query_train_same_result_with_fixed_random_state(self):
        knn_index1 = self.knn_index("euclidean", random_state=1)
        indices1, distances1 = knn_index1.build(self.x1, k=20)

        knn_index2 = self.knn_index("euclidean", random_state=1)
        indices2, distances2 = knn_index2.build(self.x1, k=20)

        np.testing.assert_equal(indices1, indices2)
        np.testing.assert_equal(distances1, distances2)

    def test_query_same_result_with_fixed_random_state(self):
        knn_index1 = self.knn_index("euclidean", random_state=1)
        indices1, distances1 = knn_index1.build(self.x1, k=30)

        knn_index2 = self.knn_index("euclidean", random_state=1)
        indices2, distances2 = knn_index2.build(self.x1, k=30)

        np.testing.assert_equal(indices1, indices2)
        np.testing.assert_equal(distances1, distances2)


class TestAnnoy(KNNIndexTestMixin, unittest.TestCase):
    knn_index = nearest_neighbors.Annoy


class TestHNSW(KNNIndexTestMixin, unittest.TestCase):
    knn_index = nearest_neighbors.HNSW


class TestBallTree(KNNIndexTestMixin, unittest.TestCase):
    knn_index = nearest_neighbors.BallTree

    def test_cosine_distance(self):
        k = 15
        # Compute cosine distance nearest neighbors using ball tree
        knn_index = nearest_neighbors.BallTree("cosine")
        indices, distances = knn_index.build(self.x1, k=k)

        # Compute the exact nearest neighbors as a reference
        true_distances = squareform(pdist(self.x1, metric="cosine"))
        true_indices_ = np.argsort(true_distances, axis=1)[:, 1:k + 1]
        true_distances_ = np.vstack([d[i] for d, i in zip(true_distances, true_indices_)])

        np.testing.assert_array_equal(
            indices, true_indices_, err_msg="Nearest neighbors do not match"
        )
        np.testing.assert_array_equal(
            distances, true_distances_, err_msg="Distances do not match"
        )

    def test_cosine_distance_query(self):
        k = 15
        # Compute cosine distance nearest neighbors using ball tree
        knn_index = nearest_neighbors.BallTree("cosine")
        knn_index.build(self.x1, k=k)

        indices, distances = knn_index.query(self.x2, k=k)

        # Compute the exact nearest neighbors as a reference
        true_distances = cdist(self.x2, self.x1, metric="cosine")
        true_indices_ = np.argsort(true_distances, axis=1)[:, :k]
        true_distances_ = np.vstack([d[i] for d, i in zip(true_distances, true_indices_)])

        np.testing.assert_array_equal(
            indices, true_indices_, err_msg="Nearest neighbors do not match"
        )
        np.testing.assert_array_equal(
            distances, true_distances_, err_msg="Distances do not match"
        )

    def test_uncompiled_callable_metric_same_result(self):
        k = 15

        knn_index = self.knn_index("manhattan", random_state=1)
        knn_index.build(self.x1, k=k)
        true_indices_, true_distances_ = knn_index.query(self.x2, k=k)

        def manhattan(x, y):
            result = 0.0
            for i in range(x.shape[0]):
                result += np.abs(x[i] - y[i])

            return result

        knn_index = self.knn_index(manhattan, random_state=1)
        knn_index.build(self.x1, k=k)
        indices, distances = knn_index.query(self.x2, k=k)
        np.testing.assert_array_equal(
            indices, true_indices_, err_msg="Nearest neighbors do not match"
        )
        np.testing.assert_allclose(
            distances, true_distances_, err_msg="Distances do not match"
        )

    def test_numba_compiled_callable_metric_same_result(self):
        k = 15

        knn_index = self.knn_index("manhattan", random_state=1)
        knn_index.build(self.x1, k=k)
        true_indices_, true_distances_ = knn_index.query(self.x2, k=k)

        @njit(fastmath=True)
        def manhattan(x, y):
            result = 0.0
            for i in range(x.shape[0]):
                result += np.abs(x[i] - y[i])

            return result

        knn_index = self.knn_index(manhattan, random_state=1)
        knn_index.build(self.x1, k=k)
        indices, distances = knn_index.query(self.x2, k=k)
        np.testing.assert_array_equal(
            indices, true_indices_, err_msg="Nearest neighbors do not match"
        )
        np.testing.assert_allclose(
            distances, true_distances_, err_msg="Distances do not match"
        )


class TestNNDescent(KNNIndexTestMixin, unittest.TestCase):
    knn_index = nearest_neighbors.NNDescent

    @patch("pynndescent.NNDescent", wraps=pynndescent.NNDescent)
    def test_random_state_being_passed_through(self, nndescent):
        random_state = 1
        knn_index = nearest_neighbors.NNDescent("euclidean", random_state=random_state)
        knn_index.build(self.x1, k=30)

        nndescent.assert_called_once()
        check_mock_called_with_kwargs(nndescent, {"random_state": random_state})

    def test_uncompiled_callable_is_compiled(self):
        knn_index = nearest_neighbors.NNDescent("manhattan")

        def manhattan(x, y):
            result = 0.0
            for i in range(x.shape[0]):
                result += np.abs(x[i] - y[i])

            return result

        compiled_metric = knn_index.check_metric(manhattan)
        self.assertTrue(isinstance(compiled_metric, CPUDispatcher))

    def test_uncompiled_callable_metric_same_result(self):
        k = 15

        knn_index = self.knn_index("manhattan", random_state=1)
        knn_index.build(self.x1, k=k)
        true_indices_, true_distances_ = knn_index.query(self.x2, k=k)

        def manhattan(x, y):
            result = 0.0
            for i in range(x.shape[0]):
                result += np.abs(x[i] - y[i])

            return result

        knn_index = self.knn_index(manhattan, random_state=1)
        knn_index.build(self.x1, k=k)
        indices, distances = knn_index.query(self.x2, k=k)
        np.testing.assert_array_equal(
            indices, true_indices_, err_msg="Nearest neighbors do not match"
        )
        np.testing.assert_allclose(
            distances, true_distances_, err_msg="Distances do not match"
        )

    def test_numba_compiled_callable_metric_same_result(self):
        k = 15

        knn_index = self.knn_index("manhattan", random_state=1)
        knn_index.build(self.x1, k=k)
        true_indices_, true_distances_ = knn_index.query(self.x2, k=k)

        @njit(fastmath=True)
        def manhattan(x, y):
            result = 0.0
            for i in range(x.shape[0]):
                result += np.abs(x[i] - y[i])

            return result

        knn_index = self.knn_index(manhattan, random_state=1)
        knn_index.build(self.x1, k=k)
        indices, distances = knn_index.query(self.x2, k=k)
        np.testing.assert_array_equal(
            indices, true_indices_, err_msg="Nearest neighbors do not match"
        )
        np.testing.assert_allclose(
            distances, true_distances_, err_msg="Distances do not match"
        )

    @patch("pynndescent.NNDescent", wraps=pynndescent.NNDescent)
    def test_building_with_lt15_builds_proper_graph(self, nndescent):
        knn_index = nearest_neighbors.NNDescent("euclidean")
        indices, distances = knn_index.build(self.x1, k=10)

        self.assertEqual(indices.shape, (self.x1.shape[0], 10))
        self.assertEqual(distances.shape, (self.x1.shape[0], 10))
        self.assertFalse(np.all(indices[:, 0] == np.arange(self.x1.shape[0])))

        # Should be called with 11 because nearest neighbor in pynndescent is itself
        check_mock_called_with_kwargs(nndescent, dict(n_neighbors=11))

    @patch("pynndescent.NNDescent", wraps=pynndescent.NNDescent)
    def test_building_with_gt15_calls_query(self, nndescent):
        nndescent.query = MagicMock(wraps=nndescent.query)
        knn_index = nearest_neighbors.NNDescent("euclidean")
        indices, distances = knn_index.build(self.x1, k=30)

        self.assertEqual(indices.shape, (self.x1.shape[0], 30))
        self.assertEqual(distances.shape, (self.x1.shape[0], 30))
        self.assertFalse(np.all(indices[:, 0] == np.arange(self.x1.shape[0])))

        # The index should be built with 15 neighbors
        check_mock_called_with_kwargs(nndescent, dict(n_neighbors=15))
        # And subsequently queried with the correct number of neighbors. Check
        # for 31 neighbors because query will return the original point as well,
        # which we don't consider.
        check_mock_called_with_kwargs(nndescent.query, dict(k=31))

    @patch("pynndescent.NNDescent", wraps=pynndescent.NNDescent)
    def test_runs_with_correct_njobs_if_dense_input(self, nndescent):
        knn_index = nearest_neighbors.NNDescent("euclidean", n_jobs=2)
        knn_index.build(self.x1, k=5)
        check_mock_called_with_kwargs(nndescent, dict(n_jobs=2))

    @patch("pynndescent.NNDescent", wraps=pynndescent.NNDescent)
    def test_runs_with_correct_njobs_if_sparse_input(self, nndescent):
        x_sparse = sp.csr_matrix(self.x1)
        knn_index = nearest_neighbors.NNDescent("euclidean", n_jobs=2)
        knn_index.build(x_sparse, k=5)
        check_mock_called_with_kwargs(nndescent, dict(n_jobs=2))

    def test_random_cluster_when_invalid_indices(self):
        class MockIndex:
            def __init__(self, data, n_neighbors, **_):
                n_samples = data.shape[0]

                rs = check_random_state(0)
                indices = rs.randint(0, n_samples, size=(n_samples, n_neighbors))
                distances = rs.exponential(5, (n_samples, n_neighbors))

                # Set some of the points to have invalid indices
                indices[:10] = -1
                distances[:10] = -1

                self.neighbor_graph = indices, distances

        with patch("pynndescent.NNDescent", wraps=MockIndex):
            knn_index = nearest_neighbors.NNDescent("euclidean", n_jobs=2)
            indices, distances = knn_index.build(self.x1, k=5)

            # Check that indices were replaced by something
            self.assertTrue(np.all(indices[:10] != -1))
            # Check that that "something" are all indices of failed points
            self.assertTrue(np.all(indices[:10] < 10))
            # And check that the distances were set to something positive
            self.assertTrue(np.all(distances[:10] > 0))
