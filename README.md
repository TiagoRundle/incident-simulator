# Incident Simulator

**CONTENT WARNING**

This repository contains detailed reconstructions of real-world school shootings. Some readers may find this material disturbing or distressing. Viewer discretion is advised.

<br>

## Ethical Use & Disclaimer

This project is intended solely for research, education, analysis, and the development of technologies aimed at improving safety and reducing harm.

The authors and contributors do not condone, promote, encourage, or endorse violence of any kind. The datasets and software in this repository document historical acts of violence for legitimate research purposes and should not be interpreted as instructional material or as support for violent activity.

The information contained in these datasets has been reconstructed from publicly available reports and documents and may contain inaccuracies, estimates, omissions, or other errors. It should not be treated as a definitive record of any incident.

By accessing or using this repository, users are responsible for ensuring that their use of the software and data is lawful, ethical, and consistent with its intended research and educational purposes. The authors, contributors, affiliated institutions, and funding organizations are not responsible for misuse of the data or software, or for actions taken by third parties based on information contained in this repository.

<br>

## Background

This project was completed to support research on autonomous robotic systems designed to impede active shooters in schools.

The purpose of the project is to document the events of historical school shootings at high fidelity so that the resulting data can be used to support research into models that better predict shooter movement and behavior.

This work was funded by a grant from the National Science Foundation.

<br>

## Incident Simulator

Throughout this project, the Incident Simulator served as a tool for both dataset creation and data visualization.

### Live Demo

A hosted demonstration version of the Incident Simulator is available here:

**https://incident-simulator.streamlit.app/**

The hosted version is intended for testing, demonstration, and educational use. Changes made to the data in the Demo Version are temporary and are not permanently saved.

To create, edit, and permanently save datasets, download or clone this repository and run the Incident Simulator locally.

<br>

## Running Locally

To create, modify, and permanently save datasets, clone or download the repository and run the Incident Simulator locally.

Install the required dependencies:

```bash
pip install -r requirements.txt
```

Then launch the application with Streamlit:

```bash
streamlit run incident_simulator.py
```

If the Python filename differs in your copy of the repository, replace the filename above with the appropriate application filename.

When running locally, changes made to datasets can be saved to their corresponding `saved_movement.csv` files.

<br>

## Datasets

This repository contains spatiotemporal datasets that reconstruct the events of historical school shootings on a second-by-second timeline.

The datasets record estimated `(X, Y)` grid positions over time for shooters and victims. They also include estimated timing information associated with events such as shots fired, injuries, and deaths.

The repository currently contains datasets for the following 9 historical incidents:

* 2002 Erfurt School
* 2005 Red Lake
* 2007 Virginia Tech
* 2012 Sandy Hook
* 2017 Aztec High
* 2018 Kerch Polytechnic
* 2021 Oxford High
* 2024 Apalachee High
* 2025 Florida State

The timelines were reconstructed using available investigative reports, official documents, and other relevant source material.

Where exact movement or timing information was unavailable, gaps in the timeline were generally filled using linear interpolation. In other cases, estimates were made based on what was considered the most plausible reconstruction given the available evidence.

As a result, these datasets should be understood as research reconstructions rather than definitive representations of the incidents. They may contain inaccuracies, uncertain estimates, incomplete information, or errors of varying degrees.

<br>

## Responsible Use

Users of this repository are expected to handle the subject matter responsibly and with appropriate respect for the victims, families, communities, and others affected by the incidents represented in these datasets.

This project exists to support research intended to improve safety and reduce harm. Use of the software or datasets for malicious, harmful, unlawful, or violent purposes is contrary to the intent of this project.
