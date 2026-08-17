---
annotations_creators:
- crowdsourced
license: other
pretty_name: DocLayNet
size_categories:
- 10K<n<100K
tags:
- layout-segmentation
- COCO
- document-understanding
- PDF
task_categories:
- object-detection
- image-segmentation
task_ids:
- instance-segmentation
dataset_info:
  features:
  - name: image
    dtype: image
  - name: bboxes
    sequence:
      sequence: float64
  - name: category_id
    sequence: int64
  - name: segmentation
    sequence:
      sequence:
        sequence: float64
  - name: area
    sequence: float64
  - name: pdf_cells
    list:
      list:
      - name: bbox
        sequence: float64
      - name: font
        struct:
        - name: color
          sequence: int64
        - name: name
          dtype: string
        - name: size
          dtype: float64
      - name: text
        dtype: string
  - name: metadata
    struct:
    - name: coco_height
      dtype: int64
    - name: coco_width
      dtype: int64
    - name: collection
      dtype: string
    - name: doc_category
      dtype: string
    - name: image_id
      dtype: int64
    - name: num_pages
      dtype: int64
    - name: original_filename
      dtype: string
    - name: original_height
      dtype: float64
    - name: original_width
      dtype: float64
    - name: page_hash
      dtype: string
    - name: page_no
      dtype: int64
  splits:
  - name: train
    num_bytes: 28172005254.125
    num_examples: 69375
  - name: test
    num_bytes: 1996179229.125
    num_examples: 4999
  - name: val
    num_bytes: 2493896901.875
    num_examples: 6489
  download_size: 7766115331
  dataset_size: 32662081385.125
---

# Dataset Card for DocLayNet v1.1

## Table of Contents
- [Table of Contents](#table-of-contents)
- [Dataset Description](#dataset-description)
  - [Dataset Summary](#dataset-summary)
  - [Supported Tasks and Leaderboards](#supported-tasks-and-leaderboards)
- [Dataset Structure](#dataset-structure)
  - [Data Fields](#data-fields)
  - [Data Splits](#data-splits)
- [Dataset Creation](#dataset-creation)
  - [Annotations](#annotations)
- [Additional Information](#additional-information)
  - [Dataset Curators](#dataset-curators)
  - [Licensing Information](#licensing-information)
  - [Citation Information](#citation-information)
  - [Contributions](#contributions)

## Dataset Description

- **Homepage:** https://developer.ibm.com/exchanges/data/all/doclaynet/
- **Repository:** https://github.com/DS4SD/DocLayNet
- **Paper:** https://doi.org/10.1145/3534678.3539043

### Dataset Summary

DocLayNet provides page-by-page layout segmentation ground-truth using bounding-boxes for 11 distinct class labels on 80863 unique pages from 6 document categories. It provides several unique features compared to related work such as PubLayNet or DocBank:

1. *Human Annotation*: DocLayNet is hand-annotated by well-trained experts, providing a gold-standard in layout segmentation through human recognition and interpretation of each page layout
2. *Large layout variability*: DocLayNet includes diverse and complex layouts from a large variety of public sources in Finance, Science, Patents, Tenders, Law texts and Manuals
3. *Detailed label set*: DocLayNet defines 11 class labels to distinguish layout features in high detail.
4. *Redundant annotations*: A fraction of the pages in DocLayNet are double- or triple-annotated, allowing to estimate annotation uncertainty and an upper-bound of achievable prediction accuracy with ML models
5. *Pre-defined train- test- and validation-sets*: DocLayNet provides fixed sets for each to ensure proportional representation of the class-labels and avoid leakage of unique layout styles across the sets.


## Dataset Structure

This dataset is structured differently from the other repository [ds4sd/DocLayNet](https://huggingface.co/datasets/ds4sd/DocLayNet), as this one includes the content (PDF cells) of the detections, and abandons the COCO format.

* `image`: page PIL image.
* `bboxes`: a list of layout bounding boxes.
* `category_id`: a list of class ids corresponding to the bounding boxes.
* `segmentation`: a list of layout segmentation polygons.
* `pdf_cells`: a list of lists corresponding to `bbox`. Each list contains the PDF cells (content) inside the bbox.
* `metadata`: page and document metadetails.

Bounding boxes classes / categories:

```
1: Caption
2: Footnote
3: Formula
4: List-item
5: Page-footer
6: Page-header
7: Picture
8: Section-header
9: Table
10: Text
11: Title
```


The `["metadata"]["doc_category"]` field uses one of the following constants:

```
* financial_reports,
* scientific_articles,
* laws_and_regulations,
* government_tenders,
* manuals,
* patents
```


### Data Splits

The dataset provides three splits
- `train`
- `val`
- `test`

## Dataset Creation

### Annotations

#### Annotation process

The labeling guideline used for training of the annotation experts are available at [DocLayNet_Labeling_Guide_Public.pdf](https://raw.githubusercontent.com/DS4SD/DocLayNet/main/assets/DocLayNet_Labeling_Guide_Public.pdf).


#### Who are the annotators?

Annotations are crowdsourced.


## Additional Information

### Dataset Curators

The dataset is curated by the [Deep Search team](https://ds4sd.github.io/) at IBM Research.
You can contact us at [deepsearch-core@zurich.ibm.com](mailto:deepsearch-core@zurich.ibm.com).

Curators:
- Christoph Auer, [@cau-git](https://github.com/cau-git)
- Michele Dolfi, [@dolfim-ibm](https://github.com/dolfim-ibm)
- Ahmed Nassar, [@nassarofficial](https://github.com/nassarofficial)
- Peter Staar, [@PeterStaar-IBM](https://github.com/PeterStaar-IBM)

### Licensing Information

License: [CDLA-Permissive-1.0](https://cdla.io/permissive-1-0/)


### Citation Information


```bib
@article{doclaynet2022,
  title = {DocLayNet: A Large Human-Annotated Dataset for Document-Layout Segmentation},
  doi = {10.1145/3534678.353904},
  url = {https://doi.org/10.1145/3534678.3539043},
  author = {Pfitzmann, Birgit and Auer, Christoph and Dolfi, Michele and Nassar, Ahmed S and Staar, Peter W J},
  year = {2022},
  isbn = {9781450393850},
  publisher = {Association for Computing Machinery},
  address = {New York, NY, USA},
  booktitle = {Proceedings of the 28th ACM SIGKDD Conference on Knowledge Discovery and Data Mining},
  pages = {3743–3751},
  numpages = {9},
  location = {Washington DC, USA},
  series = {KDD '22}
}
```