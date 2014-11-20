import numpy as np
import warnings
from scipy.sparse import issparse
from scipy.sparse.linalg import eigsh
from scipy.linalg import eigh
from sklearn.decomposition import KernelPCA

from analysis import shortest_path, laplacian

__all__ = [
    'isomap', 'laplacian_eigenmaps', 'locality_preserving_projections',
    'laplacian_pca', 'circular_layout', 'spring_layout'
]


def isomap(G, num_vecs=None, directed=True):
  directed = directed and G.is_directed()
  W = -0.5 * shortest_path(G, directed=directed) ** 2
  return KernelPCA(n_components=num_vecs, kernel='precomputed').fit_transform(W)


def laplacian_eigenmaps(G, num_vecs=None, return_vals=False, val_thresh=1e-8):
  L = laplacian(G, normed=True)
  return _lapeig(L, num_vecs, return_vals, val_thresh)


def locality_preserving_projections(G, coordinates, num_vecs=None):
  X = np.atleast_2d(coordinates)  # n x d
  L = laplacian(G, normed=True)  # n x n
  u,s,_ = np.linalg.svd(X.T.dot(X))
  Fplus = np.linalg.pinv(u * np.sqrt(s))  # d x d
  n, d = X.shape
  if n >= d:  # optimized order: F(X'LX)F'
    T = Fplus.dot(X.T.dot(L).dot(X)).dot(Fplus.T)
  else:  # optimized order: (FX')L(XF')
    T = Fplus.dot(X.T).dot(L).dot(X.dot(Fplus.T))
  L = 0.5*(T+T.T)
  return _lapeig(L, num_vecs, False, 1e-8)


def laplacian_pca(G, coordinates, num_vecs=None, beta=0.5):
  '''Graph-Laplacian PCA (CVPR 2013).
  Assumes coordinates are mean-centered.
  Parameter beta in [0,1], scales how much PCA/LapEig contributes.
  Returns an approximation of input coordinates, ala PCA.'''
  X = np.atleast_2d(coordinates)
  L = laplacian(G, normed=True)
  kernel = X.dot(X.T)
  kernel /= eigsh(kernel, k=1, which='LM', return_eigenvectors=False)
  L /= eigsh(L, k=1, which='LM', return_eigenvectors=False)
  W = (1-beta)*(np.identity(kernel.shape[0]) - kernel) + beta*L
  vals, vecs = eigh(W, eigvals=(0, num_vecs-1), overwrite_a=True)
  return X.T.dot(vecs).dot(vecs.T).T


def _lapeig(L, num_vecs, return_vals, val_thresh):
  if issparse(L):
    # This is a bit of a hack. Make sure we end up with enough eigenvectors.
    k = L.shape[0] - 1 if num_vecs is None else num_vecs + 1
    try:
      # TODO: try using shift-invert mode (sigma=0?) for speed here.
      vals,vecs = eigsh(L, k, which='SM')
    except:
      warnings.warn('Sparse eigsh failed, falling back to dense version')
      vals,vecs = eigh(L.A, overwrite_a=True)
  else:
    vals,vecs = eigh(L, overwrite_a=True)
  # vals not guaranteed to be in sorted order
  idx = np.argsort(vals)
  vecs = vecs.real[:,idx]
  vals = vals.real[idx]
  # discard any with really small eigenvalues
  i = np.searchsorted(vals, val_thresh)
  if num_vecs is None:
    # take all of them
    num_vecs = vals.shape[0] - i
  embedding = vecs[:,i:i+num_vecs]
  if return_vals:
    return embedding, vals[i:i+num_vecs]
  return embedding


def circular_layout(G):
  n = G.num_vertices()
  t = np.linspace(0, 2*np.pi, n+1)[:n]
  return np.column_stack((np.cos(t), np.sin(t)))


def spring_layout(G, num_dims=2, spring_constant=None, iterations=50,
                  initial_temp=0.1):
  """Position nodes using Fruchterman-Reingold force-directed algorithm.

  spring_constant : float (default=None)
     Optimal distance between nodes.  If None the distance is set to
     1/sqrt(n) where n is the number of nodes.  Increase this value
     to move nodes farther apart.

  iterations : int  optional (default=50)
     Number of iterations of spring-force relaxation

  initial_temp : float (default=0.1)
     Largest step-size allowed in the dynamics, decays linearly.
     Must be positive, should probably be less than 1.
  """
  X = np.random.random((G.num_vertices(), num_dims))
  if spring_constant is None:
    # default to sqrt(area_of_viewport / num_vertices)
    spring_constant = X.shape[0] ** -0.5
  S = G.matrix(csr=True, csc=True, coo=True)
  S.data[:] = 1. / S.data  # Convert to similarity
  ii,jj = S.nonzero()  # cache nonzero indices
  # simple cooling scheme, linearly steps down
  cooling_scheme = np.linspace(initial_temp, 0, iterations+2)[:-2]
  # this is still O(V^2)
  # could use multilevel methods to speed this up significantly
  for t in cooling_scheme:
    delta = X[:,None] - X[None]
    distance = _bounded_norm(delta, 1e-8)
    # repulsion from all vertices
    force = spring_constant**2 / distance
    # attraction from connected vertices
    force[ii,jj] -= S.data * distance[ii,jj]**2 / spring_constant
    displacement = np.einsum('ijk,ij->ik', delta, force)
    # update positions
    length = _bounded_norm(displacement, 1e-2)
    X += displacement * t / length[:,None]
  return X


def _bounded_norm(X, min_length):
  length = np.linalg.norm(X, ord=2, axis=-1)
  np.maximum(length, min_length, out=length)
  return length
