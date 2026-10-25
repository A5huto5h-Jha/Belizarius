
import { useState } from 'react'
import belizariusImage from './assets/belizarius.jpg'
import './App.css'

function App() {
  const [mood, setMood] = useState('IDLE')

  return (
    <main className="companion">
      <div className={`aura aura-${mood.toLowerCase()}`} />

      <img
        className="character"
        src={belizariusImage}
        alt="Belizarius"
        draggable={false}
      />

      <section className="companion-ui">
        <div className="name">BELIZARIUS</div>
        <div className="status">{mood}</div>

        <div className="controls">
          <button onClick={() => setMood('LISTENING')}>
            Listen
          </button>
          <button onClick={() => setMood('THINKING')}>
            Think
          </button>
          <button onClick={() => setMood('IDLE')}>
            Idle
          </button>
        </div>
      </section>
    </main>
  )
}

export default App
