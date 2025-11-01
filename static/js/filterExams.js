function filterExams() {
    let selectedCategories = [];
    let selectedGrades = [];
    let selectedYears = [];

    document.querySelectorAll('.filter-checkbox:checked').forEach((checkbox) => {
        let filterType = checkbox.getAttribute('data-filter');
        if (filterType === "category") {
            selectedCategories.push(checkbox.value);
        } else if (filterType === "grade") {
            selectedGrades.push(checkbox.value);
        } else if (filterType === "year") {
            selectedYears.push(checkbox.value);
        }
    });

    let queryParams = new URLSearchParams();
    if (selectedCategories.length) queryParams.append("categories", selectedCategories.join(","));
    if (selectedGrades.length) queryParams.append("grades", selectedGrades.join(","));
    if (selectedYears.length) queryParams.append("years", selectedYears.join(","));

    window.location.href = "?" + queryParams.toString();
}