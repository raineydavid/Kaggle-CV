import copy

import pandas as pd
from matplotlib import pyplot as plt

from sklearn.utils import shuffle
from tqdm import tqdm_notebook as tqdmn

def permutation_importance(model, x_que, x_pro, y, fn):
    '''
    Calculate model feature importances via random permutations of feature values
    '''
    base_loss = model.evaluate([x_que, x_pro], y)
    losses = []
    max_len = len(y)
    for i, name in enumerate(tqdmn(fn['que'] + fn['pro'])):
        n_tests, loss = 5, 0
        for j in range(n_tests):
            x_que_i, x_pro_i = copy.deepcopy(x_que), copy.deepcopy(x_pro)
            
            if name in fn['que']:
                for l in range(max_len):
                    x_que_i[l][:, i] = shuffle(x_que_i[l][:, i])
            else:
                for l in range(max_len):
                    x_pro_i[l][:, :, i - len(fn['que'])] = shuffle(x_pro_i[l][:, :, i - len(fn['que'])])
            loss += model.evaluate([x_que_i, x_pro_i], y)
            
        losses.append(loss/ n_tests)

    fi = pd.DataFrame({'importance': losses}, index=fn['que'] + fn['pro'])
    fi.sort_values(by='importance', inplace=True, ascending=False)
    fi['importance'] -= base_loss

    return fi


def plot_fi(fi, fn, title='Feature importances via shuffle', xlabel='Change in loss after shuffling feature\'s values'):
    '''
    Nicely plot Pandas DataFrame with feature importances
    '''
    fi['color'] = 'b'
    fi.loc[fi.index.isin(fn['text']), 'color'] = 'r'
    fig, ax = plt.subplots(figsize=(8, 20))
    plt.barh(fi.index, fi.importance, color=fi.color)
    plt.title(title)
    plt.xlabel(xlabel)
    ax.yaxis.tick_right()


def vis_emb(model, layer, names, figsize, colors, title, s=None):
    '''
    Visualize embeddings of a single feature
    '''
    emb = (model.get_layer(layer).get_weights()[0])
    fig, ax = plt.subplots(figsize=figsize)
    ax.scatter(emb[:, 0], emb[:, 1], c=colors, s=s)
    for i, name in enumerate(names):
        ax.annotate(name, (emb[i, 0], emb[i, 1]))
    plt.title(title)