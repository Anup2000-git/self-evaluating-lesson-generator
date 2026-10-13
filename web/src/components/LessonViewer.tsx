import { useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Lesson, QuizQuestion } from "../api/types";
import { Icon } from "./Icon";

const KIND_LABEL: Record<string, string> = {
  hook: "Start here",
  what: "What it is",
  why: "Why it matters",
  how: "How it works",
  example: "Worked example",
  misconceptions: "Common mistakes",
  summary: "Summary",
};

function Quiz({ question, index }: { question: QuizQuestion; index: number }) {
  const [picked, setPicked] = useState<number | null>(null);
  const answered = picked !== null;
  return (
    <div className="quiz-question">
      <p>
        {index + 1}. {question.question}
      </p>
      <div className="quiz-options">
        {question.options.map((option, i) => {
          const state =
            answered && i === question.correct_option_index ? "correct" : answered && i === picked ? "wrong" : "";
          return (
            <button key={i} type="button" className={`quiz-option ${state}`} disabled={answered} onClick={() => setPicked(i)}>
              <span className="quiz-letter">{String.fromCharCode(65 + i)}</span>
              <span>{option}</span>
              {state === "correct" ? <Icon name="check" /> : state === "wrong" ? <Icon name="x" /> : null}
            </button>
          );
        })}
      </div>
      {answered ? (
        <p className="quiz-explain">
          {picked === question.correct_option_index ? "Correct! " : "Not quite. "}
          {question.explanation}
        </p>
      ) : null}
    </div>
  );
}

export function LessonViewer({ lesson, helperLanguage = "Hindi" }: { lesson: Lesson; helperLanguage?: string }) {
  return (
    <article className="lesson">
      <h1>{lesson.title}</h1>
      {lesson.learning_objectives.length ? (
        <div className="objectives">
          <strong>By the end of this lesson, you will be able to:</strong>
          <ul>
            {lesson.learning_objectives.map((o) => (
              <li key={o}>{o}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {lesson.sections.map((section, i) => (
        <section key={`${section.kind}-${i}`}>
          <h2>
            <span className="section-kind">{KIND_LABEL[section.kind] ?? section.kind}</span>
            <br />
            {section.heading}
          </h2>
          <div className="hindi">
            <Markdown remarkPlugins={[remarkGfm]}>{section.body_markdown}</Markdown>
          </div>
        </section>
      ))}
      {lesson.glossary.length ? (
        <section>
          <h2>Key words (Glossary)</h2>
          <table>
            <thead>
              <tr>
                <th>Word</th>
                <th>Simple meaning</th>
                <th>{helperLanguage}</th>
              </tr>
            </thead>
            <tbody>
              {lesson.glossary.map((g) => (
                <tr key={g.term}>
                  <td>
                    <strong>{g.term}</strong>
                  </td>
                  <td>{g.simple_meaning}</td>
                  <td className="hindi">{g.helper_meaning}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}
      {lesson.quiz.length ? (
        <section>
          <h2>Check your understanding</h2>
          {lesson.quiz.map((q, i) => (
            <Quiz key={i} question={q} index={i} />
          ))}
        </section>
      ) : null}
    </article>
  );
}
