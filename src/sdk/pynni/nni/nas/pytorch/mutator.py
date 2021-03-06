# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import logging

import torch

from nni.nas.pytorch.base_mutator import BaseMutator

logger = logging.getLogger(__name__)


class Mutator(BaseMutator):

    def __init__(self, model):
        super().__init__(model)
        self._cache = dict()

    def sample_search(self):
        """
        Override to implement this method to iterate over mutables and make decisions.

        Returns
        -------
        dict
            A mapping from key of mutables to decisions.
        """
        raise NotImplementedError

    def sample_final(self):
        """
        Override to implement this method to iterate over mutables and make decisions that is final
        for export and retraining.

        Returns
        -------
        dict
            A mapping from key of mutables to decisions.
        """
        raise NotImplementedError

    def reset(self):
        """
        Reset the mutator by call the `sample_search` to resample (for search). Stores the result in a local
        variable so that `on_forward_layer_choice` and `on_forward_input_choice` can use the decision directly.
        """
        self._cache = self.sample_search()

    def export(self):
        """
        Resample (for final) and return results.

        Returns
        -------
        dict
            A mapping from key of mutables to decisions.
        """
        return self.sample_final()

    def on_forward_layer_choice(self, mutable, *inputs):
        """
        On default, this method retrieves the decision obtained previously, and select certain operations.
        Only operations with non-zero weight will be executed. The results will be added to a list.
        Then it will reduce the list of all tensor outputs with the policy specified in `mutable.reduction`.

        Parameters
        ----------
        mutable : LayerChoice
            Layer choice module.
        inputs : list of torch.Tensor
            Inputs

        Returns
        -------
        tuple of torch.Tensor and torch.Tensor
            Output and mask.
        """
        def _map_fn(op, *inputs):
            return op(*inputs)

        mask = self._get_decision(mutable)
        assert len(mask) == len(mutable.choices), \
            "Invalid mask, expected {} to be of length {}.".format(mask, len(mutable.choices))
        out = self._select_with_mask(_map_fn, [(choice, *inputs) for choice in mutable.choices], mask)
        return self._tensor_reduction(mutable.reduction, out), mask

    def on_forward_input_choice(self, mutable, tensor_list):
        """
        On default, this method retrieves the decision obtained previously, and select certain tensors.
        Then it will reduce the list of all tensor outputs with the policy specified in `mutable.reduction`.

        Parameters
        ----------
        mutable : InputChoice
            Input choice module.
        tensor_list : list of torch.Tensor
            Tensor list to apply the decision on.

        Returns
        -------
        tuple of torch.Tensor and torch.Tensor
            Output and mask.
        """
        mask = self._get_decision(mutable)
        assert len(mask) == mutable.n_candidates, \
            "Invalid mask, expected {} to be of length {}.".format(mask, mutable.n_candidates)
        out = self._select_with_mask(lambda x: x, [(t,) for t in tensor_list], mask)
        return self._tensor_reduction(mutable.reduction, out), mask

    def _select_with_mask(self, map_fn, candidates, mask):
        if "BoolTensor" in mask.type():
            out = [map_fn(*cand) for cand, m in zip(candidates, mask) if m]
        elif "FloatTensor" in mask.type():
            out = [map_fn(*cand) * m for cand, m in zip(candidates, mask) if m]
        else:
            raise ValueError("Unrecognized mask")
        return out

    def _tensor_reduction(self, reduction_type, tensor_list):
        if reduction_type == "none":
            return tensor_list
        if not tensor_list:
            return None  # empty. return None for now
        if len(tensor_list) == 1:
            return tensor_list[0]
        if reduction_type == "sum":
            return sum(tensor_list)
        if reduction_type == "mean":
            return sum(tensor_list) / len(tensor_list)
        if reduction_type == "concat":
            return torch.cat(tensor_list, dim=1)
        raise ValueError("Unrecognized reduction policy: \"{}\"".format(reduction_type))

    def _get_decision(self, mutable):
        """
        By default, this method checks whether `mutable.key` is already in the decision cache,
        and returns the result without double-check.

        Parameters
        ----------
        mutable : Mutable

        Returns
        -------
        object
        """
        if mutable.key not in self._cache:
            raise ValueError("\"{}\" not found in decision cache.".format(mutable.key))
        result = self._cache[mutable.key]
        logger.debug("Decision %s: %s", mutable.key, result)
        return result
