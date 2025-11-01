document.addEventListener("DOMContentLoaded", function() {
    const gradeBtn = document.getElementById("gradeBtn");
    gradeBtn.addEventListener("click", grade);
})

function grade() {
    const questions = document.querySelectorAll('.question-box')
    const answers = [];

    questions.forEach(q => {
        const questionID = q.dataset.index;
        const questionPK = q.dataset.pk_number;
        const selected = q.querySelector('input[type="radio"]:checked');
        const answer = selected ? selected.value : null;

        answers.push({
            index : questionID,
            pk_number : questionPK,
            answer : answer
        })
    });

    const header = document.querySelector('.header');
    const year = header.dataset.year;
    const grade = header.dataset.grade;
    const month = header.dataset.month;
    const category = header.dataset.category;
    const csrftoken = document.querySelector('meta[name="csrf-token"]').getAttribute('content')

    const params = new URLSearchParams({
        year: year,
        grade: grade,
        month: month,
        category: category
    });
        
    fetch(`/exam_list_result/?&${params.toString()}`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": csrftoken
        },
        body: JSON.stringify({answers: answers})
    }).then(res=>res.json())
    .then(data => {
        data.correct_list.forEach(index => {
            const ques = document.querySelector(`.question[data-index="${index}"]`)
            if (ques) ques.style.color = "blue";
        });
        data.wrong_list.forEach(index => {
            const ques = document.querySelector(`.question[data-index="${index}"]`)
            if (ques) ques.style.color = "red";
        });
    });
}