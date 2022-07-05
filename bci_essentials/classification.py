"""


"""


# Classification tools for transforming decision blocks into predictions

# Inputs are N x M x P where N = number of channels, M = number of samples, and P = number of signals / possible selections in P300

# Outputs a predction 

import numpy as np
import random

from sklearn.model_selection import train_test_split, KFold, StratifiedKFold
from sklearn.pipeline import make_pipeline, Pipeline
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.utils import resample
from sklearn.metrics import confusion_matrix, ConfusionMatrixDisplay, precision_score, recall_score, accuracy_score
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn import preprocessing

from pyriemann.estimation import ERPCovariances, XdawnCovariances, Covariances
from pyriemann.tangentspace import TangentSpace
from pyriemann.classification import MDM, TSclassifier
from pyriemann.utils.viz import plot_confusion_matrix

import tensorflow as tf
from tensorflow.keras.models import Sequential, load_model
from tensorflow.keras.layers import Activation, Dense, Flatten
from tensorflow.keras.optimizers import Adam
from tensorflow.keras.metrics import categorical_crossentropy

from scipy import signal

#from mne.decoding import CSP

from bci_essentials.visuals import *
from bci_essentials.signal_processing import *

# TODO : move this to signal processing???
def lico(X,y,expansion_factor=3, sum_num=2, shuffle=False):
    """
    Oversampling (linear combination oversampling (LiCO))
    X - data array
    y - label array
    expansion_factor - number of times larger to make the output set over_X
    sum_num - number of signals to be summed together
    """
    true_X = X[y == 1]

    n,m,p = true_X.shape
    print("Shape of ERPs only ", true_X.shape)
    new_n = n*np.round(expansion_factor-1)
    new_X = np.zeros([new_n,m,p])
    for i in range(n):
        for j in range(sum_num):
            new_X[i,:,:] += true_X[random.choice(range(n)),:,:] / sum_num

    over_X = np.append(X,new_X,axis=0)
    over_y = np.append(y,np.ones([new_n]))

    return over_X, over_y
    

# Write function that add to training set, fit, and predict

# make a generic classifier which can be extended to more specific classifiers
class generic_classifier():
    #
    def __init__(self, training_selection=0):
        print("initializing the classifier")
        self.X = []
        self.y = []

        #
        self.subset_defined = False
        self.subset = []

        # Lists for plotting classifier performance over time
        self.offline_accuracy = []
        self.offline_precision = []
        self.offline_recall = []
        self.offline_window_count = 0
        self.offline_window_counts = []

        # For iterative fitting,
        self.next_fit_window = 0

        # Keep track of predictions
        self.predictions = []
        self.pred_probas = []
    
    # add training data, to the training set using a decision block and a label
    def add_to_train(self, decision_block, labels, num_options = 0, meta = []):
        print("adding to training set")
        # reshape from [n,m,p] to [p,n,m]
        # n = number of channels
        # m = number of samples
        # p = number of signals
        p,n,m = decision_block.shape
        # n,m,p = decision_block.shape

        self.num_options = num_options
        self.meta = meta

        # decision_block_reshape = np.swapaxes(np.swapaxes(decision_block,0,2),1,2)

        #print(labels)
            
        if self.X == []:
            self.X = decision_block
            self.y = labels

        else:
            # print(self.X.shape)
            # print(self.y.shape)
            self.X = np.append(self.X, decision_block, axis=0)
            self.y = np.append(self.y, labels, axis=0)

    # predict a label based on a decision block
    def predict_decision_block(self, decision_block):
        print("making a prediction")

        # # reshape from [n,m,p] to [p,n,m]
        # n,m,p = decision_block.shape
        #decision_block_reshape = np.swapaxes(np.swapaxes(decision_block,0,2),1,2)

        # # get prediction probabilities for all 
        # proba_mat = self.clf.predict_proba(decision_block_reshape)

        # decision_block = np.swapaxes(np.swapaxes(decision_block,0,2),1,2)

        # get prediction probabilities for all 
        proba_mat = self.clf.predict_proba(decision_block)

        proba = proba_mat[:,1]
        # print("probabilities:")
        # print(proba)

        relative_proba = proba / np.amax(proba)
        # print("relative probabiities")
        # print(relative_proba)

        log_proba = np.log(relative_proba)
        print("log relative probabilities")
        print(log_proba)

        # the selection is the highest probability

        prediction = int(np.where(proba == np.amax(proba))[0][0])

        return prediction


class erp_rg_classifier(generic_classifier):
    def set_p300_clf_settings(self, 
                                n_splits = 3,                   # number of folds for cross-validation
                                lico_expansion_factor = 1,      # Linear Combination Oversampling expansion factor is the factor by which the number of ERPs in the training set will be expanded
                                oversample_ratio = 0,           # traditional oversampling, float from 0.1-1 resulting ratio of erp class to non-erp class, 0 for no oversampling
                                undersample_ratio = 0,          # traditional undersampling, float from 0.1-1 resulting ratio of erp class to non-erp classs, 0 for no undersampling 
                                random_seed = 42                # random seed
                                ):

        self.n_splits = n_splits                    
        self.lico_expansion_factor = lico_expansion_factor
        self.oversample_ratio = oversample_ratio
        self.undersample_ratio = undersample_ratio
        self.random_seed = random_seed


    def add_to_train(self, decision_block, label_idx, reshape=True):
        print("adding to training set")
        # reshape from [n,m,p] to [p,n,m]
        # n = number of channels
        # m = number of samples
        # p = number of windows
        p,n,m = decision_block.shape

        # decision_block_reshape = np.swapaxes(np.swapaxes(decision_block,0,2),1,2)

        # get labels from label_idx
        labels = np.zeros([p])
        labels[label_idx] = 1
        print(labels)

        # oversample until classes are even
        # WE ONLY WANT TO OVERSAMPLE TRAINING DATA
        # if oversample > 0:
        #     erp_sample = decision_block[label_idx,:,:]
        #     erp_sample = erp_sample[np.newaxis, ...]
        #     print(erp_sample.shape)
        #     for i in range(oversample):
        #         decision_block = np.append(decision_block, erp_sample, axis=0)
        #         labels = np.append(labels, 1)

        # If the classifier has no data then initialize
        if self.X == []:
            self.X = decision_block
            self.y = labels

        # If the classifier already has data then append
        else:
            self.X = np.append(self.X, decision_block, axis=0)
            self.y = np.append(self.y, labels, axis=0)

    def fit(self, n_splits = 2, plot_cm=False, plot_roc=False, lico_expansion_factor = 1):
        print("Fitting the model using RG")

        print(self.X.shape, self.y.shape)

        # Define the strategy for cross validation
        cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=self.random_seed)

        # Define the classifier
        #self.clf = make_pipeline(XdawnCovariances(), TangentSpace(metric="riemann"), RandomForestClassifier(random_state=42))
        self.clf = make_pipeline(XdawnCovariances(estimator='lwf'), TangentSpace(metric="riemann"), LinearDiscriminantAnalysis(solver='eigen',shrinkage='auto'))
        # Init predictions to all false 
        preds = np.zeros(len(self.y))

        # print(self.X.shape)
        # print(self.y.shape)
        # print(self.y)

        for train_idx, test_idx in cv.split(self.X,self.y):
            y_train, y_test = self.y[train_idx], self.y[test_idx]

            X_train = self.X[train_idx]
            X_test = self.X[test_idx]

            #LICO
            print ("Before LICO: Shape X",X_train.shape,"Shape y", y_train.shape)
            if sum(y_train) > 2:
                if lico_expansion_factor > 1:
                    X_train, y_train = lico(X_train, y_train, expansion_factor=lico_expansion_factor, sum_num=2, shuffle=False)
                    print("y_train =",y_train)
            print("After LICO: Shape X",X_train.shape,"Shape y", y_train.shape)

            # Oversampling
            if self.oversample_ratio > 0:
                p_count = sum(y_train)
                n_count = len(y_train) - sum(y_train)

                num_to_add = int(np.floor((self.oversample_ratio * n_count) - p_count))

                # Add num_to_add random selections from the positive 
                true_X_train = X_train[y_train == 1]

                len_X_train = len(true_X_train)

                for s in range(num_to_add):
                    to_add_X = true_X_train[random.randrange(0,len_X_train),:,:]

                    X_train = np.append(X_train,to_add_X[np.newaxis,:],axis=0)
                    y_train = np.append(y_train,[1],axis=0)
                

            # Undersampling
            if self.undersample_ratio > 0:
                p_count = sum(y_train)
                n_count = len(y_train) - sum(y_train)

                num_to_remove = int(np.floor(n_count - (p_count / self.undersample_ratio)))

                ind_range = np.arange(len(y_train))
                ind_list = list(ind_range)
                to_remove = []

                # Remove num_to_remove random selections from the negative
                false_ind = list(ind_range[y_train == 0])

                for s in range(num_to_remove):
                    # select a random value from the list of false indices
                    remove_at = false_ind[random.randrange(0,len(false_ind))]

                    # remove that value from the false ind list
                    false_ind.remove(remove_at)
                    #to_remove.append(remove_at)

                    # add the index to be removed to a list
                    to_remove.append(remove_at)

                    #np.delete(false_ind,remove_at,axis=0)
                    
                    #ind_range

                    #np.delete(X_train,remove_at,axis=0)

                #X_train = X_train[false]
                #X_train = X_train[]

                remaining_ind = ind_list
                for i in range(len(to_remove)):
                    remaining_ind.remove(to_remove[i])

                X_train = X_train[remaining_ind,:,:]
                y_train = y_train[remaining_ind]


            self.clf.fit(X_train, y_train)
            preds[test_idx] = self.clf.predict(X_test)
            predproba = self.clf.predict_proba(X_test)

            # Use pred proba to show what would be predicted
            predprobs = predproba[:,1]
            real = np.where(y_test == 1)

            #TODO handle exception where two probabilities are the same
            prediction = int(np.where(predprobs == np.amax(predprobs))[0][0])

            print("y_test =",y_test)

            print(predproba)
            print(real[0])
            print(prediction)

            # a,pred_proba[test_idx] = self.clf.predict_proba(self.X[test_idx])
            # print(preds[test_idx])
            # print(predproba)

        # Print performance stats
        # accuracy
        accuracy = sum(preds == self.y)/len(preds)
        self.offline_accuracy = accuracy
        print("accuracy = {}".format(accuracy))

        # precision
        precision = precision_score(self.y,preds)
        self.offline_precision = precision
        print("precision = {}".format(precision))

        # recall
        recall = recall_score(self.y, preds)
        self.offline_recall = recall
        print("recall = {}".format(recall))

        # confusion matrix in command line
        cm = confusion_matrix(self.y, preds)
        self.offline_cm = cm
        print("confusion matrix")
        print(cm)


        if plot_cm == True:
            cm = confusion_matrix(self.y, preds)
            ConfusionMatrixDisplay(cm).plot()
            plt.show()

        if plot_roc == True:
            print("plotting the ROC...")
            print("just kidding ROC has not been implemented")

# SSVEP Classifier
class ssvep_basic_classifier(generic_classifier):
    """
    Classifies SSVEP based on relative band power at the expected frequencies
    """

    def set_ssvep_settings(self, n_splits=3, sampling_freq=256, target_freqs = [1, 2, 3, 4, 5, 6, 7, 8, 9], subset=[], random_seed=42, clf_type="Random Forest"):
        self.sampling_freq = sampling_freq
        self.target_freqs = target_freqs

        # Build the cross-validation split
        self.n_splits = n_splits
        self.cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=random_seed)
        self.subset = subset

        # Define the classifier
        if clf_type == "LDA":
            self.clf = LinearDiscriminantAnalysis(solver='eigen',shrinkage='auto')

        if clf_type == "Random Forest":
            self.clf = RandomForestClassifier(n_estimators=100)



    def fit(self):
        # get dimensions
        nwindows, nchannels, nsamples = self.X.shape 

        print("Target freqs:", self.target_freqs)

        # do the rest of the training if train_free is false
        self.X = np.array(self.X)
        self.X = self.X[:,:,:]

        if self.subset != []:
            subX = self.X[:,self.subset,:]

        else:
            subX = self.X

        

        # Extract features, the bandpowers of the bands around each of the target frequencies

        # Get the PSD of the windows using Welch's method
        f, Pxx = signal.welch(subX, fs=self.sampling_freq, nperseg=256)

        # X features are the PSDs from 0 to the max target frequency + some buffer
        upper_buffer = 5
        newf = f[f < (np.amax(self.target_freqs) + upper_buffer)]

        self.Xfeatures = Pxx[:,:,len(newf)]

        # Init predictions to all false 
        preds = np.zeros(nwindows)
        predproba = np.zeros((nwindows,len(self.target_freqs)))

        for train_idx, test_idx in self.cv.split(self.Xfeatures,self.y):
            y_train, y_test = self.y[train_idx], self.y[test_idx]

            train_data = self.Xfeatures[train_idx,:]


            self.clf.fit(train_data, y_train)
            preds[test_idx] = self.clf.predict(self.Xfeatures[test_idx])
            #predproba[test_idx] = self.clf.predict_proba(self.Xfeatures[test_idx])



        # for train_idx, test_idx in self.cv.split(subX,suby):
        #     X_train, X_test = subX[train_idx], subX[test_idx]
        #     y_train, y_test = suby[train_idx], suby[test_idx]

        #     # get the covariance matrices for the training set
        #     X_train_cov = Covariances().transform(X_train)
        #     X_test_cov = Covariances().transform(X_test)

        #     # fit the classsifier
        #     self.clf.fit(X_train_cov, y_train)
        #     preds[test_idx] = self.clf.predict(X_test_cov)

        # # Print performance stats
        # # accuracy
        # correct = preds == self.y
        #print(correct)

        self.offline_window_count = nwindows
        self.offline_window_counts.append(self.offline_window_count)

        # accuracy
        accuracy = sum(preds == self.y)/len(preds)
        self.offline_accuracy.append(accuracy)
        print("accuracy = {}".format(accuracy))

        # # precision
        # precision = precision_score(self.y,preds)
        # self.offline_precision.append(precision)
        # print("precision = {}".format(precision))

        # # recall
        # recall = recall_score(self.y, preds)
        # self.offline_recall.append(recall)
        # print("recall = {}".format(recall))

        # confusion matrix in command line
        cm = confusion_matrix(self.y, preds)
        self.offline_cm = cm
        print("confusion matrix")
        print(cm)

        # if plot_cm == True:
        #     cm = confusion_matrix(self.y, preds)
        #     ConfusionMatrixDisplay(cm).plot()
        #     plt.show()

    def predict(self, X = None):

        if type(X) == None:
            X = self.X

        if self.subset != []:
            subX = X[:,self.subset,:]

        else:
            subX = X

        # Extract features, the bandpowers of the bands around each of the target frequencies

        # Get the PSD of the windows using Welch's method
        f, Pxx = signal.welch(subX, fs=self.sampling_freq, nperseg=256)

        # X features are the PSDs from 0 to the max target frequency + some buffer
        upper_buffer = 5
        newf = f[f < (np.amax(self.target_freqs) + upper_buffer)]

        Xfeatures = Pxx[:,:,len(newf)]

        # predicts for each window
        preds = self.clf.predict(Xfeatures)
        print(preds)


        # predict the value from predictions which appear in the most windows
        pred_counts = [0] * 99
        for i in range(preds.size):
            pred_counts[int(preds[i])] += 1

        #print(pred_counts)

        prediction = 0
        for i in pred_counts:
            if pred_counts[i+1] > pred_counts[prediction]:
                prediction = i+1

        # Print the predictions for sanity
        #print(preds)
        print(prediction)

        return prediction

# Train free classifier
# SSVEP CCA Classifier Sans Training
class ssvep_basic_classifier_tf(generic_classifier):
    """
    Classifies SSVEP based on relative bandpower, taking only the maximum
    """

    def set_ssvep_settings(self, sampling_freq, target_freqs):
        self.sampling_freq = sampling_freq
        self.target_freqs = target_freqs
        self.setup = False

    def fit(self):
        print("Oh deary me you must have mistaken me for another classifier which requires training")
        print("I DO NOT NEED TRAINING.")
        print("THIS IS MY FINAL FORM")

    def predict(self, X):
        # get the shape
        nwindows, nchannels, nsamples = X.shape
        # The first time it is called it must be set up
        if self.setup == False:
            print("setting up the training free classifier")

            self.setup = True

        # Build one augmented channel, here by just adding them all together
        X = np.mean(X, axis=1)

        # Get the PSD estimate using Welch's method
        f, Pxx = signal.welch(X, fs=self.sampling_freq, nperseg=256)
        
        # Get a vote for each window
        votes = np.ndarray(nwindows)
        for w in range(nwindows):
            # Get the frequency with the greatest PSD
            max_psd_freq = f[np.where(Pxx[w,:] == np.amax(Pxx[w,:]))]


            dist = np.ndarray((len(self.target_freqs), 1))

            # Calculate the minimum distance from each of the target freqs to the max_psd_freq
            for tf in self.target_freqs:
                dist = np.abs(max_psd_freq - tf)

            votes[np.where(dist == np.amin(dist))] += 1
            
        prediction = np.where(votes == np.amax(votes))

        print(prediction)

        return prediction

# TODO : Add a SSVEP CCA Classifier

class mi_classifier(generic_classifier):
    def set_mi_classifier_settings(self, n_splits=3, type="TS", subset=[], pred_threshold=0.5, subtract_center=False, rebuild = True, random_seed = 42):
        # Build the cross-validation split
        self.n_splits = n_splits
        self.cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=random_seed)

        # Initialize the classifier type
        ts = TSclassifier()
        mdm = MDM(metric=dict(mean='riemann', distance='riemann'))
        lr = LogisticRegression()
        #csp = CSP()

        # Tangent Space Logistic Regression
        if type == "TS":
            ts = TSclassifier()
            self.clf_model = Pipeline([("Tangent Space", ts)])
            self.clf = Pipeline([("Tangent Space", ts)])

        # Minimum Distance to Mean 
        elif type == "MDM":
            self.clf_model = Pipeline([("MDM", mdm)])
            self.clf = Pipeline([("MDM", mdm)])

        # CSP + Logistic Regression (REQUIRES MNE CSP)
        # elif type == "CSP-LR":
        #     self.clf_model = Pipeline([('CSP', csp), ('LogisticRegression', lr)])
        #     self.clf = Pipeline([('CSP', csp), ('LogisticRegression', lr)])

        else:
            print("Classifier type not defined") 


        # Define a subset
        if self.subset != []:
            self.subset_defined = True
            self.subset = subset
        else:
            self.subset_defined = False

        # Threshold
        self.pred_threshold = pred_threshold

        # Centerline subtraction
        self.subtract_center = subtract_center

        # Rebuild from scratch with each training
        self.rebuild = rebuild



    def fit(self):
        # get dimensions
        nwindows, nchannels, nsamples = self.X.shape 

        # do the rest of the training if train_free is false
        self.X = np.array(self.X)

        # take a subset / do spatial filtering
        self.X = self.X[:,:,:]

        # Subtract the center

        # Try rebuilding the classifier each time
        if self.rebuild == True:
            self.next_fit_window = 0
            self.clf = self.clf_model

        # 
        if self.subset_defined:
            subX = self.X[self.next_fit_window:,self.subset,:]
            suby = self.y[self.next_fit_window:]
            self.next_fit_window = nwindows

        else:
            subX = self.X[self.next_fit_window:,:,:]
            suby = self.y[self.next_fit_window:]
            self.next_fit_window = nwindows

        # plot_window(subX[0,:,:], 1)


        # currently only works with Dion's MI montage
        if self.subtract_center == True:
            try:
                subX = subX - subX[:,[1,1,1,6,6,6,6,6,6,6,12,12,12,12,12,15],:]
                subX = subX[:,[0,2,3,4,5,7,8,9,10,11,13,14],:]
            except:
                print("Centerline subtraction not possible with montage subsets")

        # plot_window(subX[0,:,:], 1)


        # Init predictions to all false 
        preds = np.zeros(nwindows)

        
        for train_idx, test_idx in self.cv.split(subX,suby):
            X_train, X_test = subX[train_idx], subX[test_idx]
            y_train, y_test = suby[train_idx], suby[test_idx]

            # get the covariance matrices for the training set
            X_train_cov = Covariances().transform(X_train)
            X_test_cov = Covariances().transform(X_test)

            # fit the classsifier
            self.clf.fit(X_train_cov, y_train)
            preds[test_idx] = self.clf.predict(X_test_cov)

            # Use pred proba to show what would be predicted
            #predprobs = predproba[:,1]
            #real = np.where(y_test == 1)

            # a,pred_proba[test_idx] = self.clf.predict_proba(self.X[test_idx])
            # print(preds[test_idx])
            # print(predproba)

        # for train_idx, test_idx in self.cv.split(self.X,self.y):
        #     X_train, X_test = self.X[train_idx], self.X[test_idx]
        #     y_train, y_test = self.y[train_idx], self.y[test_idx]

        #     # get the covariance matrices for the training set
        #     X_train_cov = Covariances().transform(X_train)
        #     X_test_cov = Covariances().transform(X_test)

        #     # fit the classsifier
        #     self.clf.fit(X_train_cov, y_train)
        #     preds[test_idx] = self.clf.predict(X_test_cov)

        #     # Use pred proba to show what would be predicted
        #     #predprobs = predproba[:,1]
        #     #real = np.where(y_test == 1)

        #     # a,pred_proba[test_idx] = self.clf.predict_proba(self.X[test_idx])
        #     # print(preds[test_idx])
        #     # print(predproba)


        # Print performance stats
        # accuracy
        correct = preds == self.y
        #print(correct)

        self.offline_window_count = nwindows
        self.offline_window_counts.append(self.offline_window_count)

        # accuracy
        accuracy = sum(preds == self.y)/len(preds)
        self.offline_accuracy.append(accuracy)
        print("accuracy = {}".format(accuracy))

        # precision
        precision = precision_score(self.y,preds)
        self.offline_precision.append(precision)
        print("precision = {}".format(precision))

        # recall
        recall = recall_score(self.y, preds)
        self.offline_recall.append(recall)
        print("recall = {}".format(recall))

        # confusion matrix in command line
        cm = confusion_matrix(self.y, preds)
        self.offline_cm = cm
        print("confusion matrix")
        print(cm)

    def predict(self, X):
        # if X is 2D, make it 3D with one as first dimension
        if len(X.shape) < 3:
            X = X[np.newaxis, ...]

        if self.subset_defined:
            X = X[:,self.subset,:]

        # Troubleshooting
        #X = self.X[-6:,:,:]

        if self.subtract_center == True:
            try:
                X = X - X[:,[1,1,1,6,6,6,6,6,6,6,12,12,12,12,12,15],:]
                X = X[:,[0,2,3,4,5,7,8,9,10,11,13,14],:]
            except:
                print("Centerline subtraction not possible with montage subsets")

        print("the shape of X is", X.shape)

        X_cov = Covariances().transform(X)
        #X_cov = X_cov[0,:,:]

        pred = self.clf.predict(X_cov)
        pred_proba = self.clf.predict_proba(X_cov)

        for i in range(len(pred)):
            self.predictions.append(pred[i])
            self.pred_probas.append(pred_proba[i])

        # add a threhold
        #pred = (pred_proba[:] >= self.pred_threshold).astype(int) # set threshold as 0.3

        return pred

class switch_classifier(generic_classifier):
    def set_switch_classifier_settings(self, n_splits = 3, rebuild = True, random_seed = 42, activation_main = 'relu', activation_class = 'softmax'):
        self.n_splits = n_splits
        self.cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=random_seed)
        self.rebuild = rebuild

        # CHANGE THE CLASSIFIER HERE IF YOU WANT
        self.adamclf = Sequential([
            Flatten(),
            Dense(units=8, input_shape=(4,), activation=activation_main),
            Dense(units=16, activation=activation_main),
            Dense(units=2, activation=activation_class)
        ])

    # fit is a little different for the switch, becouse it consists of fitting multiple binary classifiers, one for each object in the scene
    def fit(self):
        # get dimensions
        nwindows, nchannels, nsamples = self.X.shape 

        # do the rest of the training if train_free is false
        self.X = np.array(self.X)
        
        # find the number of classes in y there shoud be N + 1, where N is the number of objects in the scene and also the number of classifiers
        self.num_classifiers = len(list(np.unique(self.y))) - 1
        print(f"Number of classes: {self.num_classifiers}")

        # classifier number
        self.clf = self.adamclf

        # make a list to hold all of the classifiers
        self.clfs = []

        # loop through and build the classifiers
        for i in range(self.num_classifiers):
            # add the basic unfit classifier
            self.clfs.append(self.clf)
             
            X = self.X[0]
            y = self.y[i+1]

            # # Init predictions to all neutral (ie. zeros)
            # preds = np.zeros(nwindows)

            self.next_fit_window = 0

            preds = np.array([])

            # subX = X[self.next_fit_window:,:]
            # suby = y[self.next_fit_window:]
            self.next_fit_window = nwindows

            for train_idx, test_idx in self.cv.split(X,y):
                X_train, X_test = X[train_idx], X[test_idx]
                y_train, y_test = y[train_idx], y[test_idx]

                z_dim, y_dim, x_dim = X_train.shape
                X_train = X_train.reshape(z_dim, x_dim*y_dim)
                scaler_train = preprocessing.StandardScaler().fit(X_train)
                X_train_scaled = scaler_train.transform(X_train)

                z_dim, y_dim, x_dim = X_test.shape
                X_test = X_test.reshape(z_dim, x_dim*y_dim)
                scaler_test = preprocessing.StandardScaler().fit(X_test)
                X_test_scaled = scaler_test.transform(X_test)

                # get the covariance matrices for the training set
                '''X_train_cov = Covariances().transform(X_train)
                X_test_cov = Covariances().transform(X_test) '''

                # Compile the model
                self.adamclf.compile(optimizer=Adam(learning_rate=0.001), loss='sparse_categorical_crossentropy', metrics=['accuracy'])
                # Fit the model
                self.adamclf.fit(x=X_train_scaled, y=y_train, batch_size=5, epochs=3, shuffle=True, verbose=2, validation_data=(X_test_scaled, y_test)) # Need to reshape X_train

                # Predict
                np.append(preds, self.adamclf.predict(X_test))
                #preds[test_idx] = self.clf.predict(X_test_cov)

                # JUST ADDING A NOTE HERE THAT IN THE FUTURE WE WILL PROBABLY WANT TO USE PREDPROBA TO RETURN A SCORE FOR EACH CLASS AND NOT JUST A CLASSIFICATION

                # Use pred proba to show what would be predicted
                #predprobs = predproba[:,1]
                #real = np.where(y_test == 1)

                # a,pred_proba[test_idx] = self.clf.predict_proba(self.X[test_idx])
                # print(preds[test_idx])
                # print(predproba)

            # # Print performance stats
            # # accuracy
            # correct = preds == self.y
            # #print(correct)

            # self.offline_window_count = nwindows
            # self.offline_window_counts.append(self.offline_window_count)

            # # accuracy
            # accuracy = sum(preds == self.y)/len(preds)
            # self.offline_accuracy.append(accuracy)
            # print("accuracy = {}".format(accuracy))

            # # precision
            # precision = precision_score(self.y,preds)
            # self.offline_precision.append(precision)
            # print("precision = {}".format(precision))

            # # recall
            # recall = recall_score(self.y, preds)
            # self.offline_recall.append(recall)
            # print("recall = {}".format(recall))

            # # confusion matrix in command line
            # cm = confusion_matrix(self.y, preds)
            # self.offline_cm = cm
            # print("confusion matrix")
            # print(cm)

    # This is the predict function
    def predict(self, X):
        # if X is 2D, make it 3D with one as first dimension
        if len(X.shape) < 3:
            X = X[np.newaxis, ...]

        print("the shape of X is", X.shape)

        activationString = ""

        # THIS IS A DUMMY CLASSIFIER
        for i in range(0, self.num_classifiers):
            if i > 0:
                activationString = activationString + ","

            activationString = activationString + str(random.uniform(0, 1))


        return activationString




class null_classifier(generic_classifier):
    def fit(self):

        print("This is a null classifier, there is no fitting")

    def predict(self, X):
        return 0
