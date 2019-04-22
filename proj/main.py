import os
import pickle

import pandas as pd

from nlp import pipeline_d2v, pipeline_lda
from processors import QueProc, StuProc, ProProc
from generator import BatchGenerator
from models import DistanceModel, SimpleModel, ConcatModel, Adam
from evaluation import permutation_importance, plot_fi
from utils import TextProcessor

pd.set_option('display.max_columns', 100, 'display.width', 1024)
pd.options.mode.chained_assignment = None

DATA_PATH, SPLIT_DATE, TO_DUMP = '../../data/', '2019-01-01', True

tp = TextProcessor()

# ######################################################################################################################
#
#                                                       READ
#
# ######################################################################################################################

answers = pd.read_csv(os.path.join(DATA_PATH, 'answers.csv'), parse_dates=['answers_date_added'])
answers['answers_body'] = answers['answers_body'].apply(tp.process)
ans_train = answers[answers['answers_date_added'] < SPLIT_DATE]

questions = pd.read_csv(os.path.join(DATA_PATH, 'questions.csv'), parse_dates=['questions_date_added'])
questions['questions_title'] = questions['questions_title'].apply(tp.process)
questions['questions_body'] = questions['questions_body'].apply(tp.process)
questions['questions_whole'] = questions['questions_title'] + ' ' + questions['questions_body']
que_train = questions[questions['questions_date_added'] < SPLIT_DATE]

professionals = pd.read_csv(os.path.join(DATA_PATH, 'professionals.csv'), parse_dates=['professionals_date_joined'])
professionals['professionals_headline'] = professionals['professionals_headline'].apply(tp.process)
professionals['professionals_industry'] = professionals['professionals_industry'].apply(tp.process)
pro_train = professionals[professionals['professionals_date_joined'] < SPLIT_DATE]

students = pd.read_csv(os.path.join(DATA_PATH, 'students.csv'), parse_dates=['students_date_joined'])
stu_train = students[students['students_date_joined'] < SPLIT_DATE]

tags = pd.read_csv(os.path.join(DATA_PATH, 'tags.csv'))
tags['tags_tag_name'] = tags['tags_tag_name'].apply(lambda x: tp.process(x, allow_stopwords=True))

tag_que = pd.read_csv(os.path.join(DATA_PATH, 'tag_questions.csv')) \
    .merge(tags, left_on='tag_questions_tag_id', right_on='tags_tag_id')
tag_pro = pd.read_csv(os.path.join(DATA_PATH, 'tag_users.csv')) \
    .merge(tags, left_on='tag_users_tag_id', right_on='tags_tag_id')

# ######################################################################################################################
#
#                                                       TRAIN
#
# ######################################################################################################################

print('TRAIN')

# calculate and save tag and industry embeddings on train data
# tag_embs, ind_embs, ques_d2v = pipeline_d2v(que_train, ans_train, pro_train, tag_que, 10)
# lda_dic, lda_tfidf, lda_model = pipeline_lda(que_train, 10)

# if TO_DUMP:
#     with open(r'..\..\d2v_lda.pkl', 'wb') as file:
#         pickle.dump((ind_embs, lda_dic, lda_model, lda_tfidf, ques_d2v, tag_embs), file)

with open(r'..\..\d2v_lda.pkl', 'rb') as file:
    ind_embs, lda_dic, lda_model, lda_tfidf, ques_d2v, tag_embs = pickle.load(file)

# extract and preprocess feature for all three main entities

que_proc = QueProc(tag_embs, ques_d2v, lda_dic, lda_tfidf, lda_model)
que_data = que_proc.transform(que_train, tag_que)

stu_proc = StuProc()
stu_data = stu_proc.transform(stu_train, que_train, ans_train)

pro_proc = ProProc(tag_embs, ind_embs)
pro_data = pro_proc.transform(pro_train, que_train, ans_train, tag_pro)

# ######################################################################################################################
#
#                                                       INGESTION
#
# ######################################################################################################################

print('INGESTION')

# construct dataframe used to extract positive pairs
pairs_df = questions.merge(answers, left_on='questions_id', right_on='answers_question_id') \
    .merge(professionals, left_on='answers_author_id', right_on='professionals_id') \
    .merge(students, left_on='questions_author_id', right_on='students_id')

pairs_df = pairs_df[['questions_id', 'students_id', 'professionals_id', 'answers_date_added']]

# extract positive pairs
pos_pairs = list(pairs_df.loc[pairs_df['answers_date_added'] < SPLIT_DATE].itertuples(index=False, name=None))

# mappings from professional's id to his registration date. Used in batch generator
pro_to_date = {row['professionals_id']: row['professionals_date_joined'] for i, row in professionals.iterrows()}

bg = BatchGenerator(que_data, stu_data, pro_data, 64, pos_pairs, pos_pairs, pro_to_date)

# ######################################################################################################################
#
#                                                       MODEL
#
# ######################################################################################################################

# in train mode, build, compile train and save model
model = DistanceModel(que_dim=len(que_data.columns) - 2 + len(stu_data.columns) - 2,
                      que_input_embs=[102, 42], que_output_embs=[2, 2],
                      pro_dim=len(pro_data.columns) - 2,
                      pro_input_embs=[102, 102, 42], pro_output_embs=[2, 2, 2],
                      inter_dim=20, output_dim=10)

for lr, epochs in zip([0.01, 0.001, 0.0001], [5, 10, 5]):
    model.compile(Adam(lr=lr), loss='binary_crossentropy', metrics=['accuracy'])
    model.fit_generator(bg, epochs=epochs, verbose=2)

# ######################################################################################################################
#
#                                                   EVALUATION
#
# ######################################################################################################################

# dummy batch generator used to extract single big batch of data to calculate feature importance
bg = BatchGenerator(que_data, stu_data, pro_data, 1024, pos_pairs, pos_pairs, pro_to_date)

# dict with descriptions of feature names, used for visualization of feature importance
fn = {"que": list(stu_data.columns[2:]) + list(que_data.columns[2:]),
      "pro": list(pro_data.columns[2:])}

# calculate and plot feature importance
fi = permutation_importance(model, bg[0][0][0], bg[0][0][1], bg[0][1], fn, n_trials=3)
plot_fi(fi)

# ######################################################################################################################
#
#                                                       TEST
#
# ######################################################################################################################

# non-negative pairs are all known positive pairs to the moment
nonneg_pairs = pos_pairs

# extract positive pairs
pos_pairs = list(pairs_df.loc[pairs_df['answers_date_added'] >= SPLIT_DATE].itertuples(index=False, name=None))
nonneg_pairs += pos_pairs

# extract and preprocess feature for all three main entities

que_proc = QueProc(tag_embs, ques_d2v, lda_dic, lda_tfidf, lda_model)
que_data = que_proc.transform(questions, tag_que)

stu_proc = StuProc()
stu_data = stu_proc.transform(students, questions, answers)

pro_proc = ProProc(tag_embs, ind_embs)
pro_data = pro_proc.transform(professionals, questions, answers, tag_pro)

# initialize batch generator
bg = BatchGenerator(que_data, stu_data, pro_data, 64, pos_pairs, nonneg_pairs, pro_to_date)

# ######################################################################################################################
#
#                                                   EVALUATION
#
# ######################################################################################################################

loss, acc = model.evaluate_generator(bg)
print(f'Loss: {loss}, accuracy: {acc}')

# dummy batch generator used to extract single big batch of data to calculate feature importance
bg = BatchGenerator(que_data, stu_data, pro_data, 1024, pos_pairs, nonneg_pairs, pro_to_date)

# dict with descriptions of feature names, used for visualization of feature importance
fn = {"que": list(stu_data.columns[2:]) + list(que_data.columns[2:]),
      "pro": list(pro_data.columns[2:])}

# calculate and plot feature importance
fi = permutation_importance(model, bg[0][0][0], bg[0][0][1], bg[0][1], fn, n_trials=3)
plot_fi(fi)

# mappings from question's id to its author id. Used in Predictor
que_to_stu = {row['questions_id']: row['questions_author_id'] for i, row in questions.iterrows()}

if TO_DUMP:
    d = {'que_data': que_data,
         'stu_data': stu_data,
         'pro_data': pro_data,
         'que_proc': que_proc,
         'pro_proc': pro_proc,
         'que_to_stu': que_to_stu,
         'pos_pairs': pos_pairs}
    with open('dump.pkl', 'wb') as file:
        pickle.dump(d, file)
    model.save_weights('model.h5')
