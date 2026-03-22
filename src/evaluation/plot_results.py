import pandas as pd
import matplotlib.pyplot as plt
import glob
import os

def plot_latest_eval():
    # Find latest csv
    list_of_files = glob.glob('results/*.csv') 
    if not list_of_files:
        print("No results found in results/")
        return
        
    latest_file = max(list_of_files, key=os.path.getctime)
    print(f"Plotting results for: {latest_file}")
    
    df = pd.read_csv(latest_file)
    
    if df.empty:
        print("Empty dataset")
        return

    # Create figure with 2 subplots
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    
    # 1. Accuracy Pie Chart
    correct_counts = df['is_correct'].value_counts()
    labels = [f'Correct ({correct_counts.get(True, 0)})', f'Incorrect ({correct_counts.get(False, 0)})']
    colors = ['#4ade80', '#f87171'] # Green, Red
    
    # Handle case where all are True or all False
    pie_data = [correct_counts.get(True, 0), correct_counts.get(False, 0)]
    
    ax1.pie(pie_data, labels=labels, colors=colors, autopct='%1.1f%%', startangle=90, explode=(0.05, 0))
    ax1.set_title(f"Accuracy (Model: {df['solver_model'].iloc[0]} -> {df['grader_model'].iloc[0]})")
    
    # 2. Latency Histogram
    ax2.hist(df['latency'], bins=10, color='#60a5fa', edgecolor='white')
    ax2.set_title("Latency Distribution (seconds)")
    ax2.set_xlabel("Seconds")
    ax2.set_ylabel("Count")
    
    # Save
    base_name = os.path.basename(latest_file).replace('.csv', '.png')
    save_path = os.path.join('results', base_name)
    plt.tight_layout()
    plt.savefig(save_path)
    print(f"Chart saved to: {save_path}")

if __name__ == "__main__":
    plot_latest_eval()
