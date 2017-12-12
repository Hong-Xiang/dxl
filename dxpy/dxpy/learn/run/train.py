from pprint import pprint

import numpy as np
import tensorflow as tf
from dxpy.learn.session import Session
from dxpy.learn.train.summary import SummaryWriter
from dxpy.learn.utils.general import pre_work
from tqdm import tqdm
from dxpy.learn.config import config
import yaml
from dxpy.configs import configurable, ConfigsView


@configurable(ConfigsView(config).get('train'))
def get_train_configs(summary_freq=1000, save_freq=10000, steps=100000000):
    return {'summary_freq': summary_freq,
            'save_freq': save_freq,
            'steps': steps}


def train(definition_func):
    with open('dxln.yml') as fin:
        ycfg = yaml.load(fin)
    config.update(ycfg)
    pre_work()
    train_cfgs = get_train_configs()
    steps = train_cfgs['steps']
    summary_freq = train_cfgs['summary_freq']
    save_freq = train_cfgs['save_freq']
    network, summary = definition_func(ycfg)
    session = Session()
    with session.as_default():
        network.post_session_created()
        summary.post_session_created()
        session.post_session_created()

    with session.as_default():
        network.load()
        for i in tqdm(range(steps)):
            network.train()
            if i % summary_freq == 0 and i > 0:
                summary.summary()
                summary.flush()
            if i % save_freq == 0 and i > 0:
                network.save()

    with session.as_default():
        network.save()
