# Copyright (c) Microsoft Corporation and contributors.
# Licensed under the MIT License.

from typing import Union, Tuple
from .base import BaseVN
from ..embed import BaseEmbed
from ..embed import AdjacencySpectralEmbed as ase, LaplacianSpectralEmbed as lse
import numpy as np
from scipy.spatial import distance


class SpectralVertexNominator(BaseVN):
    """
    Class for spectral vertex nomination on a single graph.

    Given a graph G=(V,E) and a subset of V called S (the "seed"),
    Single Graph Vertex Nomination is the problem of ranking all V
    in order of relation to members of S.
    Spectral Vertex Nomination solves this problem by embedding G
    into a low dimensional euclidean space using any of the embedding
    algorithms (see embed documentation), and then generating a nomination
    list by some distance based algorithm. In the simplest case, for each
    seed vertex u, the other vertices are ranked in order of euclidean
    distance from u.
    There can be both attributed and unattributed cases. In the unattributed
    case, we treat each seed vertex individually and rank all vertices by distance.
    In the attributed case, subsets of the seed vertices share some attribute we
    care about. We want to rank the other vertices by the likelihood that they
    also share that attribute. Note that the unattributed problem is simply the
    attributed problem when each seed vertex has a unique attribute.
    SVN algorithms in general make the rather strong assumption that vertexes
    are likely to be related in a way that is of interest if they are close to
    each other in an embedding. This somewhat conflates the notion of relatedness
    and community membership, and is not appropriate for all Vertex Nomination
    problems.

    Parameters
    ----------
    embedding: np.ndarray, optional (default = None)
        An pre-calculated embedding may be provided, in which case
        it will be used for vertex nomination instead of embedding
        the adjacency matrix using embeder.
    embeder: str OR BaseEmbed, optional (default = 'ASE')
        May provide either a embed object or a string indicating
        which embedding method to use, which may be either
        "ASE" for Adjacency Spectral Embedding or
        "LSE" for Laplacian Spectral Embedding.
    persistent : bool, optional (default = True)
        If False, future calls to fit will overwrite an existing embedding. Must be True
        if an embedding is provided.


    Attributes
    ----------
    embedding : np.ndarray
        The spectral embedding of the graph spectral nomination will be preformed on.
    embeder : BaseEmbed
        The embed object to be used to compute the embedding.
    attr_labels : np.ndarray
        The attributes of the vertices in the seed (parameter 'y' for fit).
        Shape is (number_seed_vertices)
    unique_att : np.ndarray
        Each unique attribute represented in the seed. 1 dimensional.
    distance_matrix : np.ndarray
        The euclidean distance from each seed vertex to each vertex.
        Shape (number_vertices, number_unique_attributes) if attributed
        or Shape (number_vertices, number_seed_vertices) if unattributed.
    persistent : bool
        If False, future calls to fit will overwrite an existing embedding. Must be True
        if an embedding is provided.

    """

    def __init__(
        self,
        embedding: np.ndarray = None,
        embeder: Union[str, BaseEmbed] = "ASE",
        persistent: bool = True,
    ):
        super().__init__(multigraph=False)
        self.embedding = embedding
        if self.embedding is None or not persistent:
            if issubclass(type(embeder), BaseEmbed):
                self.embeder = embeder
            elif embeder == "ASE":
                self.embeder = ase()
            elif embeder == "LSE":
                self.embeder = lse()
            else:
                raise TypeError
        elif np.ndim(embedding) != 2:
            raise IndexError("embedding must have dimension 2")
        self.persistent = persistent
        self.attr_labels = None
        self.unique_att = None
        self.distance_matrix = None

    @staticmethod
    def _make_2d(arr: np.ndarray):
        # ensures arr is two or less dimensions.
        # if 1d, adds unique at each index on
        # the second dimension.
        if not np.issubdtype(arr.dtype, np.integer):
            raise TypeError("Argument must be of type int")
        arr = np.array(arr, dtype=np.int)
        if np.ndim(arr) > 2 or (arr.ndim == 2 and arr.shape[1] > 2):
            raise IndexError("Argument must have shape (n) or (n, 1) or (n, 2).")
        elif np.ndim(arr) == 1 or arr.shape[1] == 1:
            arr = arr.reshape(-1, 1)
            arr = np.concatenate((arr, np.arange(arr.shape[0]).reshape(-1, 1)), axis=1)
        return arr

    def _pairwise_dist(self, y: np.ndarray, metric: str = "euclidean") -> np.ndarray:
        # wrapper for scipy's cdist function
        # y should give indexes
        y_vec = self.embedding[y[:, 0].astype(np.int)]
        dist_mat = distance.cdist(self.embedding, y_vec, metric=metric)
        return dist_mat

    def _embed(self, X: np.ndarray):
        if not self.multigraph:
            if not np.issubdtype(X.dtype, np.number):
                raise TypeError("Adjacency matrix should have numeric type")
            if np.ndim(X) != 2:
                raise IndexError("Argument must have dim 2")
            if X.shape[0] != X.shape[1]:
                raise IndexError("Adjacency Matrix should be square.")
        else:
            raise NotImplementedError("Multigraph SVN not implemented")

        # Embed graph if embedding not provided
        if self.embedding is None:
            self.embedding = self.embeder.fit_transform(X)

    def _predict(
        self, k: int = 5, neighbor_function: str = "sum_inverse_distance"
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Nominate vertex based on distance from the k nearest neighbors of each class.

        Parameters
        ----------
        k : int, optional (default = 5)
            Number of neighbors to consider in nearest neighbors classification
        neighbor_function : str, optional (default = "sum_inverse_distance")
            method for determining class membership based on neighbors
            options
            ------
            sum_inverse_dist :      Simplest weighted knn method, works well in the VN context because
                                    it generates a natural ordering for each vertex on each attribute represented
                                    in the seed set. For each attribute, nomination is ordered by
                                    sum of the inverse of distances to the k nearest neighbors belonging
                                    to that attribute. Degenerates to simple distance based ranking when seed is
                                    unattributed and k is equivalent to the number of seeds.
        Returns
        -------
        An tuple of two np.ndarrays, each of shape(number_vertices, number_attributes_in_seed).
        The array at index 0 is the nomination list - for each attribute column, the rows are indexes
        of vertices in original adjacency matrix ordered by liklihood of matching that attribute.
        The array at index 1 is the distances computed, where each element at (i, j) represents the
        distance metric value between vertex i and attribute j.

        """
        num_unique = self.unique_att.shape[0]
        ordered = self.distance_matrix.argsort(axis=1)
        sorted_dists = self.distance_matrix[np.arange(ordered.shape[0]), ordered.T].T
        nd_buffer = np.tile(
            self.attr_labels[ordered[:, :k]], (num_unique, 1, 1)
        ).astype(np.float64)

        # comparison taking place in 3-dim view, coordinates produced are therefore 3D
        inds = np.argwhere(nd_buffer == self.unique_att[:, np.newaxis, np.newaxis])

        # nans are a neat way to operate on attributes individually
        nd_buffer[:] = np.NaN
        nd_buffer[inds[:, 0], inds[:, 1], inds[:, 2]] = sorted_dists[
            inds[:, 1], inds[:, 2]
        ]

        # weighting function. Outer inverse for consistency, makes equivalent to simple
        # ranking by distance in unattributed case, and makes higher ranked vertices
        # naturally have lower distance metric value.
        if neighbor_function == "sum_inverse_distance":
            pred_weights = np.power(np.nansum(np.power(nd_buffer, -1), axis=2), -1).T
        else:
            raise NotImplementedError("Specified neighbor function not implemented")

        nan_inds = np.argwhere(np.isnan(pred_weights))
        pred_weights[nan_inds[:, 0], nan_inds[:, 1]] = np.inf
        vert_order = np.argsort(pred_weights, axis=0)

        inds = np.tile(self.unique_att, (1, vert_order.shape[0])).T
        inds = np.concatenate((vert_order.reshape(-1, 1), inds), axis=1)
        pred_weights = pred_weights[inds[:, 0], inds[:, 1]]
        return vert_order, pred_weights.reshape(vert_order.shape)

    def predict(self, k: int = 5):
        """
        Nominate vertex based on distance from the k nearest neighbors of each class,
        or if seed is unattributed, nominates vertices for each seed vertex.
        Wrapper for private method _predict.

        Parameters
        ----------
        k : Number of neighbors to consider if seed is attributed. Otherwise is ignored.

        Returns
        -------
        An tuple of two np.ndarrays, each of shape(number_vertices, number_attributes_in_seed) if attributed,
        or shape(number_vertices, number_vertices_in_seed) if unattributed.
        The array at index 0 is the nomination list. Each column is an attribute or seed vertex, and the
        rows of each column is a list of vertex indexes from the original adjacency matrix in order degree of
        match.
        """
        if type(k) is not int:
            raise TypeError("k must be an integer")
        elif k <= 0:
            raise ValueError("k must be greater than 0")
        if self.unique_att.shape[0] == self.attr_labels.shape[0]:
            # seed is not attributed
            return self._predict(k=self.unique_att.shape[0])
        else:
            # seed is attributed
            return self._predict(k=k)

    def fit(self, X: np.ndarray, y: np.ndarray):
        """
        Constructs the embedding if not provided, then calculates the pairwise distance from each
        seed to each vertex in graph.
        Parameters
        ----------
        X : np.ndarray. Adjaceny matrix representation of graph. May be None if embedding was provided.
        y: np.ndarray. List of seed vertex indices, OR List of tuples of seed vertex indices and associated attributes.

        Returns
        -------
        None
        """
        # ensure y has correct shape. If unattributed (1d)
        # add unique attribute to each seed vertex.
        y = self._make_2d(y)
        if not self.persistent or self.embedding is None:
            if X is None:
                raise ValueError(
                    "Adjacency matrix must be provided if embedding is None."
                )
            X = np.array(X)
            self._embed(X)

        self.attr_labels = y[:, 1]
        self.unique_att = np.unique(self.attr_labels)
        self.distance_matrix = self._pairwise_dist(y)

    def fit_transform(
        self, X: np.ndarray, y: np.ndarray, k: int = 5
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Calls this class' fit and then predict methods.
        Parameters
        ----------
        X : np.ndarray. Adjaceny matrix representation of graph. May be None if embedding was provided.
        y : np.ndarray. List of seed vertex indices in adjacency matrix in column 1, and associated
                        attributes in column 2, OR list of unattributed vertex indices.
        k : Number of neighbors to consider if seed is attributed. Otherwise is ignored.

        Returns
        -------
        An tuple of two np.ndarrays, each of shape(number_vertices, number_attributes_in_seed) if attributed,
        or shape(number_vertices, number_vertices_in_seed) if unattributed.
        The array at index 0 is the nomination list. Each column is an attribute or seed vertex, and the
        rows of each column is a list of vertex indexes from the original adjacency matrix in order degree of
        match.
        """
        self.fit(X, y)
        return self.predict(k=k)
