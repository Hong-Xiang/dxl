import click
from tqdm import tqdm

def infer_sino_sr(dataset, nb_samples, output):
    """
    Use network in current directory as input for inference
    """
    import tensorflow as tf
    from dxpy.learn.dataset.api import get_dataset
    from dxpy.learn.net.api import get_network
    from dxpy.configs import ConfigsView
    from dxpy.learn.config import config
    import numpy as np
    import yaml
    from dxpy.debug.utils import dbgmsg
    dbgmsg(dataset)
    data_raw = np.load(dataset)
    data_raw = {k: np.array(data_raw[k]) for k in data_raw.keys()}
    config_view = ConfigsView(config)

    def tensor_shape(key):
        shape_origin = data_raw[key].shape
        return [1] + list(shape_origin[1:3]) + [1]
    with tf.name_scope('inputs'):
        keys = ['input/image{}x'.format(2**i) for i in range(4)]
        keys += ['label/image{}x'.format(2**i) for i in range(4)]
        dataset = {k: tf.placeholder(
            tf.float32, tensor_shape(k)) for k in keys}

    network = get_network('network/srms', dataset=dataset)
    nb_down_sample = network.param('nb_down_sample')
    config = tf.ConfigProto()
    config.gpu_options.allow_growth = True
    sess = tf.train.MonitoredTrainingSession(
        checkpoint_dir='./save', config=config, save_checkpoint_secs=None)

    STAT_STD = 9.27
    STAT_MEAN = 9.76
    BASE_SHAPE = (640, 320)

    dataset_configs = config_view['dataset']['srms']
    with_noise = dataset_configs['with_poisson_noise']
    if with_noise:
        PREFIX = 'input'
    else:
        PREFIX = 'label'

    def crop_sinogram(tensor, target_shape=None):
        if target_shape is None:
            target_shape = BASE_SHAPE
        if len(tensor.shape) == 4:
            tensor = tensor[0, :, :, 0]
        o1 = (tensor.shape[0] - target_shape[0]) // 2
        o2 = (tensor.shape[1] - target_shape[1]) // 2
        return tensor[o1:-o1, o2:-o2]

    def run_infer(idx):
        input_key = '{}/image{}x'.format(PREFIX, 2**nb_down_sample)
        low_sino = np.reshape(
            data_raw[input_key][idx, :, :], tensor_shape(input_key))
        low_sino = (low_sino - STAT_MEAN) / STAT_STD
        feeds = {dataset['input/image{}x'.format(2**nb_down_sample)]: low_sino}
        inf, itp = sess.run([network['outputs/inference'],
                             network['outputs/interp']], feed_dict=feeds)
        infc = crop_sinogram(inf)
        itpc = crop_sinogram(itp)
        infc = infc * STAT_STD + STAT_MEAN
        itpc = itpc * STAT_STD + STAT_MEAN
        return infc, itpc

    phans = []
    sino_highs = []
    sino_lows = []
    sino_itps = []
    sino_infs = []
    NB_MAX = data_raw['phantom'].shape[0]
    for idx in tqdm(range(nb_samples), ascii=True):
        if idx > NB_MAX:
            import sys
            print('Index {} out of range {}, stop running and store current result...'.format(idx, NB_MAX), file=sys.stderr)
            break

        phans.append(data_raw['phantom'][idx, ...])
        sino_highs.append(crop_sinogram(
            data_raw['{}/image1x'.format(PREFIX)][idx, :, :]))
        sino_lows.append(crop_sinogram(data_raw['{}/image{}x'.format(
            PREFIX, 2**nb_down_sample)][idx, ...], [s // (2**nb_down_sample) for s in BASE_SHAPE]))
        sino_inf, sino_itp = run_infer(idx)
        sino_infs.append(sino_inf)
        sino_itps.append(sino_itp)

    results = {'phantom': phans, 'sino_itps': sino_itps,
               'sino_infs': sino_infs, 'sino_highs': sino_highs, 'sino_lows': sino_lows}
    np.savez(output, **results)

def recon_sino(sinograms_filename, nb_samples, output, recon_method):
    import numpy as np
    from dxpy.medical_image_processing.phantom import Phantom2DSpec
    from dxpy.medical_image_processing.reconstruction.parallel import reconstruction2d
    from dxpy.medical_image_processing.detector import Detector2DParallelRing
    sinograms = np.load(sinograms_filename)
    sino_highs = np.array(sinograms['sino_highs'])
    sino_lows = np.array(sinograms['sino_lows'])
    sino_infs = np.array(sinograms['sino_infs'])
    sino_itps = np.array(sinograms['sino_itps'])
    phans = np.array(sinograms['phantom'])
    nb_views_high = sino_highs.shape[1]
    nb_views_low = sino_lows.shape[1]
    nb_views_high //= 2
    nb_views_low //= 2
    sino_highs = sino_highs[:, :nb_views_high, :]
    sino_lows = sino_lows[:, :nb_views_low, :]
    sino_infs = sino_infs[:, :nb_views_high, :]
    sino_itps = sino_itps[:, :nb_views_high, :]
    sino_lows = sino_lows * nb_views_high**2 / (nb_views_low**2)
    phan_spec = Phantom2DSpec(shape=[256]*2)
    detec_high = Detector2DParallelRing(views=np.linspace(0, np.pi, nb_views_high, endpoint=False), nb_sensors=nb_views_high, sensor_width=1.0)
    detec_low = Detector2DParallelRing(views=np.linspace(0, np.pi, nb_views_low, endpoint=False), nb_sensors=nb_views_low, sensor_width=1.0*nb_views_high/nb_views_low)
    recon_highs = []
    recon_lows = []
    recon_infs = []
    recon_itps = []
    def recon_kernel(sinogram, detec):
        sinogram = np.maximum(sinogram, 0.0)
        if recon_method == 'fbp':
            recon = reconstruction2d(sinogram, detec, phan_spec)
        elif recon_method == 'sart':
            recon = reconstruction2d(sinogram, detec, phan_spec, method='SART_CUDA', iterations=100)
        recon = np.maximum(recon, 0.0)
        recon = recon / np.sum(recon) * 1e6
        return recon


    for i in tqdm(range(nb_samples), ascii=True):
        recon_highs.append(recon_kernel(sino_highs[i, ...], detec_high))
        recon_lows.append(recon_kernel(sino_lows[i, ...], detec_low))
        recon_infs.append(recon_kernel(sino_infs[i, ...], detec_high))
        recon_itps.append(recon_kernel(sino_itps[i, ...], detec_high))
    results = {'phantom': phans, 'recon_highs': recon_highs, 'recon_lows': recon_lows, 'recon_infs': recon_infs, 'recon_itps': recon_itps}
    np.savez(output, **results)



