# DONT USE THIS
# NO OFFLINE SWITCH DATA EXISTS YET

import sys
import os

# Add parent directory to path to access bci_essentials
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)),os.pardir))

# from src.bci_data import *
from bci_essentials.bci_data import *
from bci_essentials.visuals import *

# f = open("test.txt", 'w')
# sys.stdout = f

# Initialize data object
test_switch = EEG_data()

# Select a classifier
test_switch.classifier = switch_classifier()
test_switch.classifier.set_switch_classifier_settings(n_splits=3, rebuild=True, random_seed=35)

# Select a file to run, use a file that you have locally
test_switch.load_offline_eeg_data(filename  = "examples/data/mi_example.xdf")

# Run it, brrr brrr
test_switch.main(online=False, training=True)