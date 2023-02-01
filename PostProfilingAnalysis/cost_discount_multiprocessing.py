from collections import defaultdict
import os
import sys
import io
import argparse
import re
import operator

from gmon_sample_multiprocessing import histEntry, gmonSamples

class CostDiscountCalculator:
    def __init__(self, norm_samples, bug_samples):
        #calculate performance delta for the aggregation of samples
        self.norm_samples = norm_samples
        self.bug_samples = bug_samples
        self.valid_discount = 0.1
        self.max_ahead = 3
        #default discount calculated with histograms
        self.rank_counts = defaultdict(lambda:0)
        self.cost_discounts = {} 

    def set_valid_discount(self, rate):
        self.valid_discount = rate

    def portion_processing_cost(self, bug_entry, norm_entry):
        """ check the processing cost of the entries with similar ranks
        """
        pass

    def calculate_rank_counts(self, bug_hist, norm_hist):
        """count similar ranks per function in histograms
        """
        for index in range(len(bug_hist)):
            func = bug_hist[index].symbol
            lookahead = self.max_ahead
            while lookahead >= -self.max_ahead:
                try:
                    if norm_hist[index - lookahead].symbol == func:
                        self.rank_counts[func] = self.rank_counts[func] + 1
                        break
                except:
                    pass
                lookahead = lookahead - 1
        return self.rank_counts

    def aggregate_discount(self):
        """Aggragate discounts based on histograms
        """
        for bugsample in self.bug_samples.get_samples():
            for normsample in self.norm_samples.get_samples():
                bug_hist = bugsample.entries
                norm_hist = normsample.entries
                self.calculate_rank_counts(bug_hist, norm_hist)

        total = self.bug_samples.size * self.norm_samples.size
        for func, count in self.rank_counts.items():
            discount = float(count/total)
            if discount >= self.valid_discount:
                self.cost_discounts[func] = discount
        return self.cost_discounts

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Attribute variable samples to corresponding functions')
    parser.add_argument('--norm_bin', required=True, help='')
    parser.add_argument('--bug_bin', required=True, help='')
    parser.add_argument('--norms', required=True, help='')
    parser.add_argument('--bugs', required=True, help='')
    parser.add_argument('--max', default = 100, help ='maximum number of samples supported to process')
    args = parser.parse_args()

    norm_gmons = gmonSamples(args.norms, args.norm_bin, int(args.max))
    print(f'==================norm cases {norm_gmons.size}=================')
    bug_gmons = gmonSamples(args.bugs, args.bug_bin, int(args.max))
    print(f'==================bug cases {bug_gmons.size}=================')
    cost_discounts = CostDiscountCalculator(norm_gmons, bug_gmons).aggregate_discount()
    discounts = dict(sorted(cost_discounts.items(), key=lambda item: item[1], reverse = True))
    sorted_x = sorted(cost_discounts.items(), key=operator.itemgetter(1), reverse = True)
    print(f'====discounts({len(cost_discounts)})====')
    for item in sorted_x:
        print(item)
    print('====results====')
    i = 1
    for entry in bug_gmons.samples[0].entries:
        if entry.symbol in cost_discounts:
            continue
        print(f'[{i}]'),
        entry.print_entry()
        i = i + 1
