from flask import Flask, jsonify, request

app = Flask(__name__)

tasks = []

@app.route('/tasks', methods=['GET'])
def get_tasks():
    return jsonify(tasks)

@app.route('/tasks', methods=['POST'])
def add_task():
    task = request.json.get('task')
    if task:
        tasks.append(task)
        return jsonify({'status': 'Task added'}), 201
    return jsonify({'status': 'Invalid task'}), 400

if __name__ == '__main__':
    app.run(debug=True)