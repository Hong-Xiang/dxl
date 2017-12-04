import tensorflow as tf
from ..base import Model, NodeKeys
from .blocks import StackedConv2D
from .residual import StackedResidual
from ..image import align_crop
from dxpy.configs import configurable
from ...configs import config


class SRKeys:
    REPRESENTS = 'reps'
    RESIDUAL = 'resi'
    ALIGNED_LABEL = 'aligned_label'
    INTERP = 'interp'


class BuildingBlocks:
    STACKEDCONV = 'stacked_conv'
    RESCONV = 'res_conv'
    RESINCEPT = 'res_incept'
    INTERP = 'interp'


class SuperResolution2x(Model):
    def __init__(self, name, inputs, *,
                 building_block: str=None,
                 nb_layers: int=None,
                 filters: int=None,
                 boundary_crop=None,
                 **config):
        super().__init__(name, inputs,
                         building_block=building_block,
                         nb_layers=nb_layers,
                         filters=filters,
                         boundary_crop=boundary_crop,
                         **config)

    @classmethod
    def _default_config(cls):
        from dxpy.collections.dicts import combine_dicts
        return combine_dicts({
            'building_block': BuildingBlocks.STACKEDCONV,
            'nb_layers': 10,
            'filters': 32,
            'boundary_crop': [4, 4]
        }, super()._default_config())

    def _kernel(self, feeds):
        from ..image import resize, boundary_crop, mean_square_error
        with tf.variable_scope('input'):
            u = resize(feeds[NodeKeys.INPUT], (2, 2))
            if SRKeys.REPRESENTS in feeds:
                r = resize(feeds[SRKeys.REPRESENTS], (2, 2))
                r = align_crop(r, u)
                r = tf.concat([r, u], axis=3)
            else:
                r = tf.layers.conv2d(u, self.param('filters'), 5, name='stem')
        if self.param('building_block') == BuildingBlocks.STACKEDCONV:
            x = StackedConv2D('kernel', r,
                              nb_layers=self.param('nb_layers'),
                              filters=self.param('filters'))()
        elif self.param('building_block') == BuildingBlocks.RESCONV:
            x = StackedResidual('kernel', r, self.param(
                'nb_layers'), StackedResidual.STACKED_CONV_TYPE)()
        elif self.param('building_block') == BuildingBlocks.RESINCEPT:
            x = StackedResidual('kernel', r, nb_layers=self.param('nb_layers'),
                                block_type=StackedResidual.INCEPT_TYPE)()
        with tf.variable_scope('inference'):
            res = tf.layers.conv2d(x, 1, 3, padding='same')
            res = boundary_crop(res, self.param('boundary_crop'))
            u_c = align_crop(u, res)
            y = res + u_c
        result = {NodeKeys.INFERENCE: y,
                  SRKeys.REPRESENTS: x,
                  SRKeys.RESIDUAL: res,
                  SRKeys.INTERP: u_c}
        if NodeKeys.LABEL in feeds:
            with tf.name_scope('loss'):
                aligned_label = align_crop(feeds[NodeKeys.LABEL], y)
                l = mean_square_error(aligned_label, y)
            result.update({NodeKeys.LOSS: l,
                           SRKeys.ALIGNED_LABEL: aligned_label})
        return result


from ...config import config as cfg


class SuperResolutionBlock(Model):
    """
    Inputs:
        NodeKeys.INPUT: input low resolution image
        NodeKeys.LABEL: [Optional] high resolution label image
        SRKeys.REPRESENTS: [Optional] low resolution feature representations
    Outputs:
        NodeKeys.INFERENCE: high resolution image (cropped)
        NodeKeys.LOSS: REQUIRES: Inputs[NodeKeys.LABEL], loss of inference
        SRKeys.REPRESENTS: represents befefore inference image
    Sub-models:
        'kernel': One of StackedConv2D or StackedResidual 
    """

    @configurable(cfg, with_name=True)
    def __init__(self, name, inputs, *,
                 building_block: str=BuildingBlocks.STACKEDCONV,
                 nb_layers: int=10,
                 filters: int=32,
                 boundary_crop=(4, 4),
                 down_sample_ratio=(2, 2),
                 boundary_crop_ratio=0.1,
                 with_poi_loss=False,
                 poi_loss_weight=0.0,
                 **config):
        super().__init__(name, inputs,
                         building_block=building_block,
                         nb_layers=nb_layers,
                         filters=filters,
                         boundary_crop=boundary_crop,
                         boundary_crop_ratio=boundary_crop_ratio,
                         with_poi_loss=with_poi_loss,
                         poi_loss_weight=poi_loss_weight, 
                         **config)

    @classmethod
    def _default_config(cls):
        from dxpy.collections.dicts import combine_dicts
        return combine_dicts({
            'building_block': BuildingBlocks.STACKEDCONV,
            'nb_layers': 10,
            'filters': 32,
            'boundary_crop': [4, 4],
            'boundary_crop_ratio': 0.1,
            'down_sample_ratio': (2, 2)
        }, super()._default_config())

    def _crop_size(self, input_=None):
        from ..tensor import shape_as_list
        if self.param('boundary_crop') == 'relative':
            shape = shape_as_list(input_)
            ratio = self.param('boundary_crop_ratio')
            return [int(shape[0] * ratio), int(shape[1] * ratio)]
        else:
            return self.param('boundary_crop')

    def _input(self, feeds):
        """
        """
        # TODO： add check for input shape
        from ..image import resize
        from ..tensor import shape_as_list
        with tf.variable_scope('input'):
            u = resize(feeds[NodeKeys.INPUT], self.param('down_sample_ratio'))
            if self.param('building_block') == BuildingBlocks.INTERP:
                return u, None
            if SRKeys.REPRESENTS in feeds:
                r = resize(feeds[SRKeys.REPRESENTS],
                           self.param('down_sample_ratio'))
                r = align_crop(u, r)
                r = tf.concat([r, u], axis=3)
            else:
                r = tf.layers.conv2d(u, self.param(
                    'filters'), 5, name='stem', padding='same')
            if NodeKeys.LABEL in feeds:
                l = feeds[NodeKeys.LABEL]
            else:
                l = None
            return u, r, l

    def _inference(self, represents, upsampled):
        from ..image import boundary_crop, align_crop

        with tf.variable_scope('inference'):
            upsampled = boundary_crop(upsampled, self._crop_size(upsampled))
            if self.param('building_block') == BuildingBlocks.INTERP:
                return {NodeKeys.INFERENCE: upsampled}
            residual = tf.layers.conv2d(represents, 1, 3, padding='same')
            residual = align_crop(residual, upsampled)
            inference = residual + upsampled
        return {NodeKeys.INFERENCE: inference,
                SRKeys.RESIDUAL: residual,
                SRKeys.INTERP: upsampled}

    def _kernel_stacked_convolution(self, represents):
        return StackedConv2D(self.name / 'kernel', represents,
                             nb_layers=self.param('nb_layers'),
                             filters=self.param('filters'))()

    def _kernel_stacked_residual(self, represents):
        if self.param('building_block') == BuildingBlocks.RESCONV:
            block_type = StackedResidual.STACKED_CONV_TYPE
        else:
            block_type = StackedResidual.INCEPT_TYPE
        return StackedResidual(self.name / 'kernel', represents,
                               nb_layers=self.param('nb_layers'),
                               block_type=block_type)()

    def _loss(self, label, inference):
        from ..image import mean_square_error, align_crop
        from ..losses import PoissionLossWithDenorm
        if label is not None:
            with tf.name_scope('loss'):
                aligned_label = align_crop(label, inference)
                loss_mse = mean_square_error(aligned_label, inference)
                loss = loss_mse
                if self.param('with_poi_loss'):
                    loss_poi = PoissionLossWithDenorm(self.name / 'loss' / 'poi', 
                    {NodeKeys.INPUT: inference, NodeKeys.LABEL: aligned_label}).as_tensor()
                    loss = loss + self.param('poi_loss_weight')
                return {NodeKeys.LOSS: loss,
                        SRKeys.ALIGNED_LABEL: aligned_label}
        else:
            return dict()

    def _kernel(self, feeds):
        upsampled, represents, label = self._input(feeds)
        if self.param('building_block') == BuildingBlocks.INTERP:
            x = upsampled
        if self.param('building_block') == BuildingBlocks.STACKEDCONV:
            x = self._kernel_stacked_convolution(represents)
        elif self.param('building_block') in [BuildingBlocks.RESCONV, BuildingBlocks.RESINCEPT]:
            x = self._kernel_stacked_residual(represents)
        result = {SRKeys.REPRESENTS: x}
        result.update(self._inference(x, upsampled))
        result.update(self._loss(label, result[NodeKeys.INFERENCE]))
        return result


class SuperResolutionMultiScale(Model):
    """
    Inputs:
        'input/image1x'
        NodeKeys.LABEL: [Optional] high resolution label image
        SRKeys.REPRESENTS: [Optional] low resolution feature representations
    Outputs:
        NodeKeys.INFERENCE: high resolution image (cropped)
        NodeKeys.LOSS: <REQUIRED: Inputs[NodeKeys.LABEL], loss of inference
        SRKeys.REPRESENTS: represents befefore inference image
    """

    def __init__(self, name, inputs, nb_down_sample, *, share_model=None, **config):
        super().__init__(name, inputs, nb_down_sample=nb_down_sample,
                         share_model=share_model, **config)

    @classmethod
    def _default_config(cls):
        from dxpy.collections.dicts import combine_dicts
        return combine_dicts({
            'nb_down_sample': 3,
            'loss_weight': 1.0,
            'share_model': False
        }, super()._default_config())

    @classmethod
    def multi_scale_input(cls, images, nb_down_sample=None, labels=None):
        if nb_down_sample is None:
            nb_down_sample = len(images) - 1
        if labels is None:
            labels = images
        inputs = {}
        for i in range(nb_down_sample + 1):
            inputs.update({'input/image{}x'.format(2**i): images[i]})
        for i in range(nb_down_sample):
            inputs.update({'label/image{}x'.format(2**i): labels[i]})
        return inputs

    def _get_node(self, node_type, down_sample_ratio, source=None):
        if source is None:
            source = self.nodes
        name = "{}/image{}x".format(node_type, 2**down_sample_ratio)
        return source[name]

    def _kernel(self, feeds):
        x = None
        r = None
        losses = []
        for i_down_sample in reversed(range(1, self.param('nb_down_sample') + 1)):
            if x is None:
                x = self._get_node('input', i_down_sample, feeds)
            mid_result = SuperResolution2x('sr2x_{}'.format(i_down_sample),
                                           {NodeKeys.INPUT: x,
                                            NodeKeys.LABEL: self._get_node('label', i_down_sample - 1, feeds),
                                            SRKeys.REPRESENTS: r})()
            x = mid_result[NodeKeys.INFERENCE]
            if NodeKeys.LOSS in mid_result:
                losses.append(mid_result[NodeKeys.LOSS])
            r = mid_result[SRKeys.REPRESENTS]
        result = {k: mid_result[k] for k in mid_result}
        if len(losses) > 0:
            with tf.name_scope('loss'):
                if not isinstance(self.param('loss_weight'), (list, tuple)):
                    lw = [self.param('loss_weight')] * \
                        self.param('nb_down_sample')
                else:
                    lw = self.param('loss_weight')
                for i, l in enumerate(losses):
                    losses[i] = losses[i] * lw[i]
                result[NodeKeys.LOSS] = tf.add_n(losses)
        return result


import typing


class SuperResolutionMultiScalev2(Model):
    """
    Inputs:
    NodeKeys.Input: Low resolution inputs
    'input/image[1, 2, 4, 8]x': input images, only the one with largest down sample ratio is required,
    others will be ignored. 
    'input/clean[1, 2, 4, 8]x': labels, may be noisy.
    Outputs:
    NodeKeys.INFERENCE: inference image
    NodeKeys.LOSS: scalar loss 
    SRKeys.ALIGNED_LABEL: cropped label (useful for calculating residual)
    """
    @configurable(config, with_name=True)
    def __init__(self, name, inputs, *,
                 nb_down_sample: int=3,
                 share_model=False,
                 loss_weight: typing.TypeVar('T', float, typing.List[float]),
                 **config):
        super().__init__(name, inputs,
                         nb_down_sample=nb_down_sample,
                         share_model=share_model,
                         loss_weight=loss_weight,
                         **config)


    @classmethod
    def multi_scale_input(cls, images, nb_down_sample=None, labels=None):
        """
        Helper function to make valid images from varient input schemes.
        Args:
        -   images: list of input tensors. `images[-1]` should usually be the input low resolution image.
            For those case considering noise, images maybe used as training labels
        -   nb_down_sample: number of down sample operations, if is `None`, `len(images) -1` will be used.
        -   labels: list of label tensors. 
        """
        if nb_down_sample is None:
            nb_down_sample = len(images) - 1
        if labels is None:
            labels = images
        inputs = {}
        for i in range(nb_down_sample + 1):
            inputs.update({'input/image{}x'.format(2**i): images[i]})
        for i in range(nb_down_sample):
            inputs.update({'label/image{}x'.format(2**i): labels[i]})
        return inputs

    def _get_node(self, node_type, down_sample_level, source=None):
        """
        Get nodes from source dict-like object.
        Args:
        -   node_type: 'image' or 'label',
        -   down_sample_level: required down sample level, 
        -   source: dict-like object, if is `None`, use `self.nodes`
        """

        if source is None:
            source = self.nodes
        name = "{}/image{}x".format(node_type, 2**down_sample_ratio)
        return source[name]

    def _kernel(self, feeds):
        x = None
        r = None
        losses = []
        for i_down_sample in reversed(range(1, self.param('nb_down_sample') + 1)):
            if x is None:
                x = self._get_node('input', i_down_sample, feeds)
            mid_result = SuperResolution2x(self.name/'srb_{}'.format(i_down_sample),
                                           {NodeKeys.INPUT: x,
                                            NodeKeys.LABEL: self._get_node('label', i_down_sample - 1, feeds),
                                            SRKeys.REPRESENTS: r})()
            x = mid_result[NodeKeys.INFERENCE]
            if NodeKeys.LOSS in mid_result:
                losses.append(mid_result[NodeKeys.LOSS])
            r = mid_result[SRKeys.REPRESENTS]
        result = {k: mid_result[k] for k in mid_result}
        if len(losses) > 0:
            with tf.name_scope('loss'):
                if not isinstance(self.param('loss_weight'), (list, tuple)):
                    lw = [self.param('loss_weight')] * \
                        self.param('nb_down_sample')
                else:
                    lw = self.param('loss_weight')
                for i, l in enumerate(losses):
                    losses[i] = losses[i] * lw[i]
                result[NodeKeys.LOSS] = tf.add_n(losses)
        return result
