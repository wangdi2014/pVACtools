#  Input would be a protein fasta or both pvac-seq run output final.tsv and input annotated vcf
# python lib/vaccine_design.py test --generate-input-fasta -t tests/test_data/vaccine_design/input_parse_test_input.tsv -v tests/test_data/vaccine_design/input_parse_test_input.vcf ann H-2-Kb -o . -n 25 -l 8
# python lib/vaccine_design.py test -f tests/test_data/vaccine_design/Test.vaccine.results.input.fa ann H-2-Kb -o . -n 25 -l 8

import shutil
import sys
import argparse
import os
from pathlib import Path
root = str(Path(__file__).resolve().parents[1])
sys.path.append(root)

import pandas
import networkx as nx
import itertools
from Bio import SeqIO
import lib

from lib.optimal_peptide import *
from lib.vector_visualization import *
import random

from lib.prediction_class import *
from lib.run_argument_parser import *

def define_parser():
    return PvacvectorRunArgumentParser().parser

def tsvToFasta(n_mer, input_tsv, input_vcf, output_dir):

    def parse_choosen_epitopes(input_tsv):
        with open(input_tsv, 'r') as input_f:
            next(input_f)
            mut_IDs, mutations, mut_types, mt_epitope_seqs, wt_epitope_seqs, transcript_IDs = [], [], [], [], [], []
            for line in input_f:
                fields = line.split("\t")
                mut_type, mutation, pos, gene_name = fields[7], fields[8], fields[9], fields[10]
                mt_epitope_seq, wt_epitope_seq = fields[15], fields[16]
                mutations.append(mutation)
                mut_types.append(mut_type)
                mutation = mutation.split("/")
                #if position presented as a range, use higher end of range
                old_AA, new_AA = mutation[0], mutation[1]
                if "-" in pos:
                    pos = pos.split("-")
                    pos = pos[1]
                    mut_ID = ("MT." + gene_name + "." +  pos + "fs")
                elif mut_type == "FS":
                    mut_ID = "MT." + gene_name + "." + old_AA + pos + "fs"
                elif mut_type == "missense": 
                    mut_ID = "MT." + gene_name + "."  + old_AA + pos + new_AA
                mut_IDs.append(mut_ID)
                mt_epitope_seqs.append(mt_epitope_seq)
                wt_epitope_seqs.append(wt_epitope_seq)
                transcript_IDs.append(fields[5])
        input_f.close()
        return mut_IDs, mutations, mut_types, mt_epitope_seqs, wt_epitope_seqs, transcript_IDs

#get necessary data from initial pvacseq input vcf
    def parse_original_vcf(input_vcf):
        with open(input_vcf, 'r') as input_f:
            transcripts_dict = {}
            for line in input_f:
                attributes = []
                if line[0] != "#":
                    fields = line.split("\t")
                    info = fields[7]
                    info = info.split("|")
                    transcript_ID, downstr_seq, len_change, full_seq = info[6], info[23], info[24], info[25]
                    attributes.append(full_seq)
                    attributes.append(downstr_seq)
                    attributes.append(len_change)
                    transcripts_dict[transcript_ID] = attributes
        input_f.close()
        return(transcripts_dict)

    def edit_full_seq(i, mut_types, mutations, wt_epitope_seqs, mt_epitope_seqs, sub_seq, full_seq, transcripts_dict):
        if mut_types[i] == "FS":
            downstr_seq, len_change = transcripts_dict[transcript_IDs[i]][1], int(transcripts_dict[transcript_IDs[i]][2])
            parts = mutations[i].split("/")
            initial = parts[0]
            final = parts[1]

            #handle -/X mutations by appending downstr_seq to next position, instead of overwriting last position
            if initial == "-":
                new_end_of_full_seq = len(full_seq) + len_change - len(downstr_seq)
            #overwrites last position of seq with first position of
            #predicted downstr seq
            else:
                new_end_of_full_seq = len(full_seq) + len_change - len(downstr_seq) - 1
            full_seq = full_seq[:new_end_of_full_seq]
        #handles ex: L/LX mutations by adding sequence that is preserved
        #before the downstr predicted sequence
            if len(final) > 1:
                final = final.replace("X", "")
                full_seq = full_seq + final
            full_seq = full_seq + downstr_seq
        elif mut_types[i] == "missense":
            full_seq = full_seq.replace(wt_epitope_seqs[i], mt_epitope_seqs[i])
        else:
            sys.exit("Mutation not yet handled by this parser")
        return(full_seq)

    #get flanking peptides for the epitope chosen
    def get_sub_seq(full_seq, mt_seq, n_mer):
        beginning = full_seq.find(mt_seq)
        if beginning == -1:
            sys.exit("Error: could not find mutant epitope sequence in mutant full sequence")
        length = len(mt_seq)
        end = beginning + length
        #if eptitope sequence is too close to the beginning or end to get the
        #right amount of flanking peptides, get appropriate length from solely
        #ahead or behind
        len_needed = n_mer - length
        if len_needed % 2 != 0:
            front = int(beginning - len_needed / 2)
            back = int(end + len_needed / 2)
        else:
            front = int(beginning - len_needed / 2)
            back = int(end + len_needed / 2)
        if front < 0:
            sub_seq = full_seq[beginning:(beginning + n_mer)]
        elif back > len(full_seq):
            sub_seq = full_seq[(end - n_mer):end]
        else:
            sub_seq = full_seq[front:back]
        return(sub_seq)

    def write_output_fasta(output_f, n_mer, mut_IDs, mutations, mut_types, mt_epitope_seqs, wt_epitope_seqs, transcript_IDs, transcripts_dict):
        with open(output_f, 'w') as out_f:
            sub_seq = ""
            full_seq = ""
            n_mer = int(n_mer)
            for i in range(len(transcript_IDs)):
                full_seq = (transcripts_dict[transcript_IDs[i]])[0] 
            
                full_seq = edit_full_seq(i, mut_types, mutations, wt_epitope_seqs, mt_epitope_seqs, sub_seq, full_seq, transcripts_dict)

                sub_seq = get_sub_seq(full_seq, mt_epitope_seqs[i], n_mer)
                out_f.write(">" + mut_IDs[i] + "\n")
                out_f.write(sub_seq + "\n")
                print("ID: " + mut_IDs[i] + ", sequence: " + sub_seq)
        out_f.close()
        print("FASTA file written")
        return()

    output_f = os.path.join(output_dir, "vector_input.fa")

    mut_IDs, mutations, mut_types, mt_epitope_seqs, wt_epitope_seqs, transcript_IDs = parse_choosen_epitopes(input_tsv)

    transcripts_dict = parse_original_vcf(input_vcf)

    write_output_fasta(output_f, n_mer, mut_IDs, mutations, mut_types, mt_epitope_seqs, wt_epitope_seqs, transcript_IDs, transcripts_dict)
    return(output_f)

def main(args_input=sys.argv[1:]):

    parser = define_parser()
    args = parser.parse_args(args_input)

    if "." in args.sample_name:
        sys.exit("Run name cannot contain '.'")

    if args.iedb_retries > 100:
        sys.exit("The number of IEDB retries must be less than or equal to 100")

    if (os.path.splitext(args.input_file))[1] == '.fa':
        input_file = args.input_file
        generate_input_fasta = False
    elif (os.path.splitext(args.input_file))[1] == '.tsv':
        input_tsv = args.input_file
        input_vcf = args.input_vcf
        #error if tsv not provided
        generate_input_fasta = True
    else:
        sys.exit("Input file type not as expected. Needs to be a .fa or a .vcf file")
    input_n_mer = args.input_n_mer
    iedb_method = args.prediction_algorithms[0]
    ic50_cutoff = args.binding_threshold
    alleles = args.allele
    epl = args.epitope_length
    print("IC50 cutoff: " + str(ic50_cutoff))
    runname = args.sample_name
    outdir = args.output_dir

    base_output_dir = os.path.abspath(outdir)
    base_output_dir = os.path.join(base_output_dir, runname)
    tmp_dir = os.path.join(base_output_dir, runname + '_tmp')
    os.makedirs(tmp_dir, exist_ok=True)

    if args.seed_rng:
        random.seed(0.5)
    if generate_input_fasta:
        input_file = tsvToFasta(input_n_mer, input_tsv, input_vcf, base_output_dir)

    peptides = SeqIO.parse(input_file, "fasta")
   
    seq_dict = dict()
    for record in peptides:
        seq_dict[record.id] = str(record.seq)

    seq_keys = sorted(seq_dict)
    seq_tuples = list(itertools.combinations_with_replacement(seq_keys, 2))
    combinations = list()

    for key in seq_tuples:
        if key[0] != key[1]:
            combinations.append((key[0], key[1]))
            combinations.append((key[1], key[0]))
    
    seq_tuples = combinations
    epitopes = dict()
    rev_lookup = dict()

    for comb in seq_tuples:
        seq1 = comb[0]
        seq2 = comb[1]
        for length in range(8, 11):
            seq_ID = seq1 + "|" + seq2
            trunc_seq1 = seq_dict[seq1][(len(seq_dict[seq1]) - length):len(seq_dict[seq1])]
            trunc_seq2 = seq_dict[seq2][0:(length - 1)]
            epitopes[seq_ID] = trunc_seq1 + trunc_seq2
            rev_lookup[(trunc_seq1 + trunc_seq2)] = seq_ID

            spacers = ["HH", "HHC", "HHH", "HHHD", "HHHC", "AAY", "HHHH", "HHAA", "HHL", "AAL"]
            for this_spacer in spacers:
                seq_ID = seq1 + "|" + this_spacer + "|" + seq2
                epitopes[seq_ID] = (trunc_seq1 + this_spacer + trunc_seq2)
                rev_lookup[(trunc_seq1 + this_spacer + trunc_seq2)] = seq_ID

    epitopes_file = os.path.join(tmp_dir, runname + "_epitopes.fa")
    with open(epitopes_file, "w") as tmp:
        for each in epitopes:
            tmp.write(">" + each + "\n" + epitopes[each] + "\n")

    outfile = os.path.join(tmp_dir, runname + '_iedb_out.csv')
    split_out = []

    for a in alleles:
        for l in epl:
            print ("Calling iedb for " + a + " of length " + str(l))
            prediction_class = globals()[iedb_method]
            prediction = prediction_class()
            translated_iedb_method = prediction.iedb_prediction_method
            lib.call_iedb.main([
                epitopes_file,
                outfile,
                translated_iedb_method,
                a,
                '-l', str(l),
                '-r', str(args.iedb_retries), 
                '-e', args.iedb_install_directory
            ])
            with open(outfile, 'rU') as sheet:
                split_out.append(pandas.read_csv(sheet, delimiter='\t'))

    print("IEDB calls complete. Merging data.")

    with open(outfile, 'rU') as sheet:
        split_out.append(pandas.read_csv(sheet, delimiter='\t'))
    epitope_binding = pandas.concat(split_out)
    problematic_neoepitopes = epitope_binding[epitope_binding.ic50 < ic50_cutoff]
    merged = pandas.DataFrame(pandas.merge(epitope_binding, problematic_neoepitopes, how='outer',
                                           indicator=True).query('_merge == "left_only"').drop(['_merge'], axis=1))
    merged = merged.sort_values('ic50', ascending=False)
    peptides = merged.set_index('peptide').T.to_dict('dict')

    keyErrorCount = 0
    successCount = 0
    iedb_results = dict()
    for seqID in epitopes:
        for l in epl:
            for i in range(0, len(epitopes[seqID]) - (l-1)):
                key = epitopes[seqID][i:i+l]
                try:
                    peptides[key]
                except KeyError:
                    keyErrorCount += 1
                    continue

                if seqID not in iedb_results:
                    iedb_results[seqID] = {}
                allele = peptides[key]['allele']
                if allele not in iedb_results[seqID]:
                    iedb_results[seqID][allele] = {}
                    if 'total_score' not in iedb_results[seqID][allele]:
                        iedb_results[seqID][allele]['total_score'] = list()
                        iedb_results[seqID][allele]['total_score'].append(peptides[key]['ic50'])
                    else:
                        iedb_results[seqID][allele]['total_score'].append(peptides[key]['ic50'])

                if 'min_score' in iedb_results[seqID][allele]:
                    iedb_results[seqID][allele]['min_score'] = min(iedb_results[seqID][allele]['min_score'], peptides[key]['ic50'])
                else:
                    iedb_results[seqID][allele]['min_score'] = peptides[key]['ic50']
                    successCount += 1

    print("Successful ic50 mappings: " + str(successCount) + " errors: " + str(keyErrorCount))

    Paths = nx.DiGraph()
    spacers = [None, "HH", "HHC", "HHH", "HHHD", "HHHC", "AAY", "HHHH", "HHAA", "HHL", "AAL"]
    for ep in combinations:
        ID_1 = ep[0]
        ID_2 = ep[1]
        Paths.add_node(ID_1)
        Paths.add_node(ID_2)
        for space in spacers:
            if space is None:
                key = str(ID_1 + "|" + ID_2)
            else:
                key = str(ID_1 + "|" + space + "|" + ID_2)
            worst_case = sys.maxsize
            for allele in iedb_results[key]:
                if iedb_results[key][allele]['min_score'] < worst_case:
                    worst_case = iedb_results[key][allele]['min_score']
            if Paths.has_edge(ID_1, ID_2) and Paths[ID_1][ID_2]['weight'] < worst_case:
                Paths[ID_1][ID_2]['weight'] = worst_case
                if space is not None:
                    Paths[ID_1][ID_2]['spacer'] = space
                else:
                    Paths[ID_1][ID_2]['spacer'] = ''
            elif not Paths.has_edge(ID_1, ID_2):
                if space is not None:
                    Paths.add_edge(ID_1, ID_2, weight=worst_case, spacer=space)
                else:
                    Paths.add_edge(ID_1, ID_2, weight=worst_case, spacer='')

    print("Graph contains " + str(len(Paths)) + " nodes and " + str(Paths.size()) + " edges.")
    print("Finding path.")

    distance_matrix = {}
    for ID_1 in Paths:
        try:
            distance_matrix[ID_1]
        except KeyError:
            distance_matrix[ID_1] = {}
        for ID_2 in Paths[ID_1]:
            distance_matrix[ID_1][ID_2] = Paths[ID_1][ID_2]['weight']

    init_state = seq_keys
    if not args.seed_rng:
        random.shuffle(init_state)   
    peptide = OptimalPeptide(init_state, distance_matrix)
    peptide.copy_strategy = "slice"
    peptide.save_state_on_exit = False
    state, e = peptide.anneal()
    while state[0] != seq_keys[0]:
        state = state[1:] + state[:1] 
    print("%i distance :" % e)

    for id in state:
        print("\t", id)

    results_file = os.path.join(base_output_dir, runname + '_results.fa')
    with open(results_file, 'w') as f:
        name = list()
        min_score = Paths[state[0]][state[1]]['weight']
        cumulative_weight = 0
        all_scores = list()

        for i in range(0, len(state)):
            name.append(state[i])
            try:
                min_score = min(min_score, Paths[state[i]][state[i + 1]]['weight'])
                cumulative_weight += Paths[state[i]][state[i + 1]]['weight']
                all_scores.append(str(Paths[state[i]][state[i + 1]]['weight']))
                spacer = Paths[state[i]][state[i + 1]]['spacer']
                if spacer is not '':
                    name.append(spacer)
            except IndexError:
                continue
        median_score = str(cumulative_weight/len(all_scores))
        peptide_id_list = ','.join(name)
        score_list = ','.join(all_scores)
        output = list()
        output.append(">")
        output.append(peptide_id_list)
        output.append("|Median_Junction_Score:")
        output.append(median_score)
        output.append("|Lowest_Junction_Score:")
        output.append(str(min_score))
        output.append("|All_Junction_Scores:")
        output.append(score_list)
        output.append("\n")
        for id in name:
            try:
                output.append(seq_dict[id])
            except KeyError:
                output.append(id)
            output.append("\n")
        f.write(''.join(output))

    if not args.keep_tmp_files:
        shutil.rmtree(tmp_dir)

    VectorVisualization(results_file, base_output_dir).draw()

if __name__ == "__main__":
    main()

