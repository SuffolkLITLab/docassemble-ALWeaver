import re
import spacy
import numpy as np
from numpy import unique
from numpy import where
from sklearn.cluster import AffinityPropagation
from sklearn.metrics.pairwise import cosine_similarity


def reCase(text):
    # a quick and dirty way to pull words out of
    # snake_case, camelCase and the like.    
    output = re.sub("(\w|\d)(_|-)(\w|\d)","\\1 \\3",text.strip())
    output = re.sub("([a-z])([A-Z]|\d)","\\1 \\2",output)
    output = re.sub("(\d)([A-Z]|[a-z])","\\1 \\2",output)
    return output

def cluster_screens(fields=[],damping=0.9):
    # Takes in a list (fields) and returns a suggested screen grouping
    # Set damping to value >= 0.5 or < 1 to tune how related screens should be
  
    nlp = spacy.load('en_core_web_lg') # this takes a while to load

    vec_mat = np.zeros([len(fields),300])
    for i in range(len(fields)):
        vec_mat[i] = [nlp(reCase(fields[i])).vector][0]

    # create model
    model = AffinityPropagation(damping=damping,random_state=4)
    # fit the model
    model.fit(vec_mat)
    # assign a cluster to each example
    yhat = model.predict(vec_mat)
    # retrieve unique clusters
    clusters = unique(yhat)

    screens = {}
    #sim = np.zeros([5,300])
    i=0
    for cluster in clusters:
        this_screen = where(yhat == cluster)[0]
        vars = []
        j=0
        for screen in this_screen:
            #sim[screen]=vec_mat[screen] # use this spot to add up vectors for compare to list
            vars.append(fields[screen])
            j+=1
        screens["screen_%s"%i]=vars
        i+=1

    return screens